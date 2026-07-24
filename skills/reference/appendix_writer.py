"""
Pipeline stage (v3, on-demand, run AFTER a lecture deck exists): writes targeted, longer-form
appendix sections for a case study, driven by specific requests pulled from a deck's outline
markdown -- NOT an automatic pass over every (reading, topic) pair.

Reuses topic_content_extractor.py's cached map_candidates.json -- no PDF re-extraction, no
re-running the map phase. Each request's answer is grounded in the same candidate facts the
slide-facts reduce phase already saw, just synthesized toward a specific, narrow question instead
of "write an appendix for this (reading, topic) in general."

Why this exists (v3 change): an earlier version asked the slide-facts reduce call to also
produce a 150-1500 word appendix for every (reading, topic) pair, organized "as needed." In
practice this reliably produced paper-shaped summaries (Introduction/Background/Findings/
Conclusion headers) rather than material organized around mechanisms -- because it ran blind,
before any deck existed to say what was actually worth elaborating. This script fixes both
problems: it only runs for pairs a real deck flagged, and its prompt is constrained to forbid
generic paper-summary structure.

Install: pip install anthropic requests

Usage:
    python skills/appendix_writer.py --out-dir data/lecture-prep/<example-id> \
        --outline path/to/outline.md

Reads the outline markdown's "## Appendix Requests" block:
    ## Appendix Requests
    - reading: <reading_id>
      topic: <topic_id>
      ask: "<specific, narrow question>"

Writes:
    <out-dir>/appendix_content.json  -- per-request cache (reading, topic, ask) -> content
    <out-dir>/appendix.md            -- assembled document, grouped by topic (framework
                                         sequence order) then reading, one section per request
"""
import os
import re
import json
import hashlib
import argparse

import anthropic

from pipeline_common import DEFAULT_READINGS, DEFAULT_FRAMEWORK
from topic_content_extractor import (
    resolve_backend,
    model_for_backend,
    call_llm,
    extract_json_dict,
    load_json_cache,
    save_json_cache,
    load_topics_by_id,
)

APPENDIX_MAX_TOKENS = 2500

# Forbidden generic paper-summary headers -- the actual quality fix from the v3 plan. Checked
# both in the prompt (told not to use these) and, defensively, post-hoc (warn if the model uses
# one anyway, rather than silently shipping a paper-shaped section again).
FORBIDDEN_HEADERS = {
    "introduction", "background", "overview", "conclusion", "conclusions", "findings",
    "abstract", "summary", "discussion",
}

APPENDIX_PROMPT = """You are writing ONE focused section of a course appendix -- a briefing note \
answering a specific question, not a paper summary. This is for the case study "{cs_name}", \
topic "{topic_name}".

Reading: {title}
Authors: {authors}

The specific thing this section needs to answer:
"{ask}"

Candidate facts extracted from this reading (deduplicated, each tagged with its source section):
{candidates_block}

Write 150-1500 words (scale to what the ask and candidates actually support -- a narrow question \
answered well in 250 words is better than padding to a higher count). Rules:
- Open by directly answering the question above -- don't introduce the paper first.
- Organize around: the mechanism/process itself, then any criteria/thresholds/formulas involved \
(if applicable), then concrete numbers or examples. Use "##" subheadings matching THIS structure \
(e.g. "## How it works", "## Thresholds", "## In practice" -- adapt names to the actual content, \
but keep them mechanism/criteria/data-shaped).
- Do NOT use generic paper-summary headers: no "Introduction", "Background", "Overview", \
"Conclusion", "Findings", "Abstract", "Summary", or "Discussion" as section names. If context is \
genuinely needed, give it in a sentence or two of lead-in prose before the first real subheading, \
not as its own section.
- Quote liberally where useful and attribute clearly (this is a course-internal document, not \
slide text, so the usual short-quote limit doesn't apply here).
- Use ONLY the candidate material above -- don't invent content not grounded in it.

Respond with ONLY a JSON object:
{{"content": "the full markdown section, starting from the first ## subheading (no top-level title -- that's added when this is assembled into the full document)"}}
"""


# ============================================================================
# outline parsing
# ============================================================================

REQUEST_BLOCK_PATTERN = re.compile(
    r"reading:\s*(\S+)\s*\n\s*topic:\s*(\S+)\s*\n\s*ask:\s*\"([^\"]+)\"", re.MULTILINE
)


def parse_appendix_requests(outline_path):
    with open(outline_path, encoding="utf-8") as f:
        text = f.read()
    section_match = re.search(r"##\s*Appendix Requests\s*\n(.*?)(?:\n##\s|\Z)", text, re.DOTALL)
    if not section_match:
        return []
    block = section_match.group(1)
    requests = []
    for m in REQUEST_BLOCK_PATTERN.finditer(block):
        requests.append({"reading": m.group(1), "topic": m.group(2), "ask": m.group(3).strip()})
    return requests


# ============================================================================
# candidate lookup (reuses topic_content_extractor.py's map cache -- no re-extraction)
# ============================================================================

def get_candidates_for_reading(reading_id, reading, map_cache):
    cached = map_cache.get(reading_id)
    if cached and cached.get("chunks"):
        candidates = [c for chunk in cached["chunks"] for c in chunk["candidates"]]
        if candidates:
            return candidates, "map_candidates"
    abstract = reading.get("abstract")
    if abstract:
        return [{"type": "fact", "text": abstract, "location_hint": "abstract"}], "abstract_fallback"
    return [], "none"


def format_candidates_block(candidates, max_items=60):
    lines = []
    for c in candidates[:max_items]:
        loc = c.get("location_hint", "?")
        typ = c.get("type", "fact")
        lines.append(f"- [{loc} / {typ}] {c.get('text', '')}")
    return "\n".join(lines) if lines else "(no extracted candidates -- working from abstract only)"


# ============================================================================
# request cache
# ============================================================================

def request_key(reading_id, topic_id, ask):
    ask_hash = hashlib.sha256(ask.encode()).hexdigest()[:12]
    return f"{reading_id}::{topic_id}::{ask_hash}"


def check_forbidden_headers(content):
    found = []
    for line in content.splitlines():
        m = re.match(r"^#{1,3}\s+(.+)$", line.strip())
        if m and m.group(1).strip().lower() in FORBIDDEN_HEADERS:
            found.append(m.group(1).strip())
    return found


# ============================================================================
# generation
# ============================================================================

def write_appendix_section(req, reading, topic_meta, cs_name, candidates, backend,
                           anthropic_client, model_name):
    prompt = APPENDIX_PROMPT.format(
        cs_name=cs_name, topic_name=topic_meta["name"],
        title=reading.get("title", req["reading"]), authors=reading.get("authors", "?"),
        ask=req["ask"], candidates_block=format_candidates_block(candidates),
    )
    raw = call_llm(prompt, backend, anthropic_client, model_name, APPENDIX_MAX_TOKENS)
    parsed = extract_json_dict(raw)
    content = parsed.get("content", "") if parsed else ""

    bad_headers = check_forbidden_headers(content) if content else []
    if bad_headers:
        print(f"    WARNING: generic header(s) slipped through despite prompt constraint: "
              f"{bad_headers} -- consider a stricter follow-up pass or manual edit")

    return {
        "reading": req["reading"], "topic": req["topic"], "ask": req["ask"],
        "content": content, "backend": backend, "model": model_name,
        "source": None,  # filled in by caller (map_candidates vs abstract_fallback)
        "forbidden_headers_detected": bad_headers,
    }


# ============================================================================
# assembly into appendix.md
# ============================================================================

def build_appendix_markdown(cs_name, entries, readings_by_id, topics_in_sequence):
    lines = [f"# {cs_name} \u2014 Extended Notes\n"]
    lines.append("_Targeted extended notes, generated on demand from the lecture deck's own "
                 "appendix requests -- not an automatic summary of every reading._\n")

    by_topic = {}
    for e in entries:
        by_topic.setdefault(e["topic"], []).append(e)

    any_content = False
    for topic_id, topic_name in topics_in_sequence:
        topic_entries = by_topic.get(topic_id, [])
        if not topic_entries:
            continue
        any_content = True
        lines.append(f"\n## {topic_name}\n")
        for e in topic_entries:
            title = readings_by_id.get(e["reading"], {}).get("title", e["reading"])
            lines.append(f"### {title}")
            lines.append(f"*Addressing: {e['ask']}*\n")
            lines.append(e["content"].strip() + "\n")

    if not any_content:
        lines.append("\n_No appendix requests found in the outline yet._\n")
    return "\n".join(lines)


# ============================================================================
# orchestration
# ============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--outline", required=True, help="path to the deck's outline markdown "
                        "(must contain a '## Appendix Requests' block)")
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK))
    parser.add_argument("--backend", choices=("anthropic", "ollama"), default=None,
                        help="default: REDUCE_BACKEND env, else ALIGNMENT_BACKEND")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    requests = parse_appendix_requests(args.outline)
    if not requests:
        raise SystemExit(f"No '## Appendix Requests' entries found in {args.outline} -- nothing to do.")
    print(f"Found {len(requests)} appendix requests in {args.outline}")

    backend = resolve_backend(args.backend, "REDUCE_BACKEND")
    model_name = model_for_backend(backend)
    anthropic_client = anthropic.Anthropic() if backend == "anthropic" else None
    print(f"Backend: {backend} ({model_name})")

    with open(args.readings, encoding="utf-8") as f:
        readings_by_id = {r["id"]: r for r in json.load(f)["readings"]}
    topics_by_id = load_topics_by_id(args.framework)

    with open(args.framework, encoding="utf-8") as f:
        framework = json.load(f)
    topics_in_sequence = [(t["id"], t["name"]) for t in sorted(framework["topics"], key=lambda t: t["sequence"])]

    map_cache_path = os.path.join(args.out_dir, "map_candidates.json")
    map_cache = load_json_cache(map_cache_path)
    appendix_cache_path = os.path.join(args.out_dir, "appendix_content.json")
    appendix_cache = load_json_cache(appendix_cache_path)
    # appendix_content.json is a list; index it by request key for cache lookups, list on disk
    cache_by_key = {request_key(e["reading"], e["topic"], e["ask"]): e for e in appendix_cache} \
        if isinstance(appendix_cache, list) else {}

    results = []
    for req in requests:
        key = request_key(req["reading"], req["topic"], req["ask"])
        cached = cache_by_key.get(key)
        if cached and not args.force:
            print(f"  cached: {req['reading']}::{req['topic']} ({req['ask'][:50]}...)")
            results.append(cached)
            continue

        reading = readings_by_id.get(req["reading"])
        if reading is None:
            print(f"  SKIP: unknown reading id '{req['reading']}'")
            continue
        topic_meta = topics_by_id.get(req["topic"], {"name": req["topic"], "description": ""})
        candidates, source = get_candidates_for_reading(req["reading"], reading, map_cache)

        print(f"  writing: {req['reading']}::{req['topic']} ({req['ask'][:60]}...) [{source}]")
        entry = write_appendix_section(
            req, reading, topic_meta, "this case study", candidates, backend,
            anthropic_client, model_name,
        )
        entry["source"] = source
        cache_by_key[key] = entry
        results.append(entry)

    appendix_cache_list = list(cache_by_key.values())
    save_json_cache(appendix_cache_path, appendix_cache_list)

    with open(args.readings, encoding="utf-8") as f:
        readings_by_id_full = {r["id"]: r for r in json.load(f)["readings"]}
    cs_name_guess = os.path.basename(os.path.normpath(args.out_dir))
    md = build_appendix_markdown(cs_name_guess, results, readings_by_id_full, topics_in_sequence)
    appendix_md_path = os.path.join(args.out_dir, "appendix.md")
    with open(appendix_md_path, "w", encoding="utf-8") as f:
        f.write(md)

    warned = [r for r in results if r.get("forbidden_headers_detected")]
    print(f"\nDone. {len(results)} sections written to {appendix_md_path}")
    if warned:
        print(f"NOTE: {len(warned)} section(s) had a forbidden generic header slip through -- "
              f"review these by hand:")
        for w in warned:
            print(f"  {w['reading']}::{w['topic']}: {w['forbidden_headers_detected']}")


if __name__ == "__main__":
    main()
