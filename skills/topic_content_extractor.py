"""
Map-reduce topic content extraction per reading (slide-ready facts only).

Longer-form extended notes are NOT produced here (v3) -- see appendix_writer.py, run on demand
after a deck outline exists. Map cache in map_candidates.json is reused by appendix_writer.py.

Install: pip install anthropic requests

Writes:
    <out-dir>/map_candidates.json   -- chunk-level candidates (keep for appendix_writer.py)
    <out-dir>/topic_content.json    -- key_facts/mechanism/data_points per (reading, topic)
"""
import os
import re
import json
import hashlib
import argparse
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import anthropic

from pipeline_common import (
    DEFAULT_READINGS,
    DEFAULT_FRAMEWORK,
    require_anthropic_key,
    get_anthropic_model,
    get_ollama_model,
    get_map_backend,
    get_reduce_backend,
    get_section_chunks,
)
from src.ollama_client import ollama_generate, extract_json_object

MAP_MAX_TOKENS = 1200
REDUCE_MAX_TOKENS = 1200
MAX_CHUNK_CHARS = 8000

DEDUP_THRESHOLD = 0.6
STOPWORDS = {
    "the", "and", "of", "in", "using", "evidence", "from", "for", "with", "on", "to", "a", "an",
    "study", "case", "india", "indian", "analysis", "paper", "data", "new", "review", "based",
}

MAP_PROMPT = """Extract concrete, specific content from this section of an academic paper/report. \
Don't categorize by topic yet -- just pull out anything a reader would find useful: named facts, \
specific mechanisms or processes explained, numbers/statistics, and any other methodologically or \
substantively interesting nuggets.

Paper: {title}
Section: {section_name}
Section text:
{section_text}

Respond with ONLY a JSON array of candidate items (empty array if this section has nothing \
substantive -- e.g. references list, acknowledgments):
[
  {{"type": "fact|mechanism|data_point|nugget", "text": "the specific extracted content, as a self-contained sentence or two"}}
]
"""

REDUCE_PROMPT = """You are writing course material for a class on "{topic_name}" ({topic_description}), \
using the reading below as one example within the case study "{cs_name}".

Reading: {title}
Authors: {authors}

Candidate facts, mechanisms, and data points extracted from this reading (deduplicated, in no \
particular order, each tagged with the section it came from):
{candidates_block}

Using ONLY the material above (don't invent content not grounded in these candidates), produce:
1. key_facts: 3-6 short, specific, nameable facts (indicator names, variable names, sample sizes, \
named entities) a lecture slide could bullet-point.
2. mechanism: a 40-60 word slide-ready summary of how the relevant process/system actually works.
3. data_points: concrete numbers/statistics worth putting on a slide (empty list if genuinely none).

(Longer-form extended notes are handled separately, on demand, by appendix_writer.py once a
lecture deck exists and knows what it specifically needs elaborated -- don't try to produce that
here.)

Respond with ONLY a JSON object:
{{"key_facts": ["...", "..."], "mechanism": "...", "data_points": ["...", "..."]}}
"""


def resolve_map_backend(cli_value):
    if cli_value:
        return cli_value.lower()
    return get_map_backend()


def resolve_reduce_backend(cli_value):
    if cli_value:
        return cli_value.lower()
    return get_reduce_backend()


def resolve_backend(cli_value, env_var_name):
    """Shared backend resolver for appendix_writer.py (--backend uses REDUCE_BACKEND)."""
    if cli_value:
        return cli_value.lower()
    if env_var_name == "MAP_BACKEND":
        return get_map_backend()
    if env_var_name == "REDUCE_BACKEND":
        return get_reduce_backend()
    return get_reduce_backend()


def model_for_backend(backend):
    return get_ollama_model() if backend == "ollama" else get_anthropic_model()


def call_llm(prompt, backend, anthropic_client, model_name, max_tokens):
    if backend == "ollama":
        return ollama_generate(prompt, model=model_name)
    response = anthropic_client.messages.create(
        model=model_name, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def extract_json_array(raw):
    parsed = extract_json_object(raw)
    if isinstance(parsed, list):
        return parsed
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def extract_json_dict(raw):
    parsed = extract_json_object(raw)
    if isinstance(parsed, dict):
        return parsed
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def sig_words(text):
    s = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return {w for w in s.split() if len(w) >= 4 and w not in STOPWORDS}


def word_overlap_score(a, b):
    sa, sb = sig_words(a), sig_words(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def dedup_candidates(candidates, threshold=DEDUP_THRESHOLD):
    merged = []
    for c in candidates:
        text = c.get("text", "")
        if not text:
            continue
        if not any(word_overlap_score(text, m.get("text", "")) >= threshold for m in merged):
            merged.append(c)
    return merged


def load_json_cache(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json_cache(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def candidates_fingerprint(candidates):
    texts = sorted(c.get("text", "") for c in candidates)
    return hashlib.sha256(json.dumps(texts).encode()).hexdigest()[:16]


def map_cache_valid(cached_entry, backend, model_name, source_mtime, expected_chunk_count):
    if not cached_entry:
        return False
    if cached_entry.get("backend") != backend or cached_entry.get("model") != model_name:
        return False
    if cached_entry.get("source_mtime") != source_mtime:
        return False
    if len(cached_entry.get("chunks", [])) != expected_chunk_count:
        return False
    return True


def run_map_phase(reading_id, reading, entry, map_cache, backend, anthropic_client, model_name,
                  force_map):
    text_md_path = entry.get("text_md_path")
    chunks = get_section_chunks(text_md_path) if text_md_path else []

    if not chunks:
        abstract = reading.get("abstract")
        if not abstract:
            return None, False
        return [{"type": "fact", "text": abstract, "location_hint": "abstract"}], True

    source_mtime = os.path.getmtime(text_md_path)
    cached = map_cache.get(reading_id)
    if not force_map and map_cache_valid(cached, backend, model_name, source_mtime, len(chunks)):
        print(f"  map: cached ({len(chunks)} chunks): {reading_id}")
        all_candidates = [c for chunk in cached["chunks"] for c in chunk["candidates"]]
        return dedup_candidates(all_candidates), False

    print(f"  map: {len(chunks)} chunks for {reading_id} (backend={backend})")
    chunk_results = []
    for i, (section_name, section_text) in enumerate(chunks):
        prompt = MAP_PROMPT.format(
            title=reading.get("title", reading_id), section_name=section_name,
            section_text=section_text[:MAX_CHUNK_CHARS],
        )
        try:
            raw = call_llm(prompt, backend, anthropic_client, model_name, MAP_MAX_TOKENS)
            parsed = extract_json_array(raw) or []
        except Exception as e:
            print(f"    chunk {i} ({section_name}) FAILED: {e}")
            parsed = []
        for item in parsed:
            item["location_hint"] = section_name
        chunk_results.append({"chunk_index": i, "section_name": section_name, "candidates": parsed})

    map_cache[reading_id] = {
        "backend": backend, "model": model_name, "source_mtime": source_mtime,
        "chunks": chunk_results,
    }
    all_candidates = [c for chunk in chunk_results for c in chunk["candidates"]]
    return dedup_candidates(all_candidates), False


def format_candidates_block(candidates, max_items=60):
    lines = []
    for c in candidates[:max_items]:
        loc = c.get("location_hint", "?")
        typ = c.get("type", "fact")
        lines.append(f"- [{loc} / {typ}] {c.get('text', '')}")
    return "\n".join(lines)


def reduce_cache_valid(cached_entry, backend, model_name, fingerprint, force):
    if force:
        return False
    if not cached_entry or not cached_entry.get("key_facts"):
        return False
    if cached_entry.get("backend") != backend or cached_entry.get("model") != model_name:
        return False
    if cached_entry.get("candidates_fingerprint") != fingerprint:
        return False
    return True


def run_reduce_phase(reading_id, reading, topic_id, topics_by_id, cs_name, candidates,
                     topic_cache, backend, anthropic_client, model_name, force_reduce):
    cache_key = f"{reading_id}::{topic_id}"
    fingerprint = candidates_fingerprint(candidates)
    cached = topic_cache.get(cache_key)
    if reduce_cache_valid(cached, backend, model_name, fingerprint, force_reduce):
        print(f"  reduce: cached: {cache_key}")
        return cached

    topic_meta = topics_by_id.get(topic_id, {"name": topic_id, "description": ""})
    prompt = REDUCE_PROMPT.format(
        topic_name=topic_meta["name"], topic_description=topic_meta.get("description", ""),
        cs_name=cs_name, title=reading.get("title", reading_id),
        authors=reading.get("authors", "?"),
        candidates_block=format_candidates_block(candidates),
    )
    print(f"  reduce: {cache_key} (backend={backend})")
    try:
        raw = call_llm(prompt, backend, anthropic_client, model_name, REDUCE_MAX_TOKENS)
        parsed = extract_json_dict(raw)
    except Exception as e:
        parsed = None
        print(f"    FAILED: {e}")

    if parsed is None:
        result = {"note": "Reduce call failed or returned unparseable output.",
                  "backend": backend, "model": model_name}
    else:
        result = {
            "key_facts": parsed.get("key_facts", []),
            "mechanism": parsed.get("mechanism", ""),
            "data_points": parsed.get("data_points", []),
            "backend": backend, "model": model_name,
            "candidates_fingerprint": fingerprint,
        }
    topic_cache[cache_key] = result
    return result


def load_topics_by_id(framework_path):
    with open(framework_path, encoding="utf-8") as f:
        framework = json.load(f)
    return {t["id"]: {"name": t["name"], "description": t.get("description", "")}
            for t in framework["topics"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK))
    parser.add_argument("--map-backend", choices=("anthropic", "ollama"), default=None)
    parser.add_argument("--reduce-backend", choices=("anthropic", "ollama"), default=None)
    parser.add_argument("--force-map", action="store_true")
    parser.add_argument("--force-reduce", action="store_true")
    args = parser.parse_args()

    map_backend = resolve_map_backend(args.map_backend)
    reduce_backend = resolve_reduce_backend(args.reduce_backend)
    map_model = model_for_backend(map_backend)
    reduce_model = model_for_backend(reduce_backend)

    anthropic_client = None
    if "anthropic" in (map_backend, reduce_backend):
        require_anthropic_key()
        anthropic_client = anthropic.Anthropic()

    print(f"Map backend: {map_backend} ({map_model})")
    print(f"Reduce backend: {reduce_backend} ({reduce_model})")

    with open(os.path.join(args.out_dir, "access_manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    with open(args.readings, encoding="utf-8") as f:
        readings_by_id = {r["id"]: r for r in json.load(f)["readings"]}
    topics_by_id = load_topics_by_id(args.framework)

    cs_name = manifest.get("case_study_id", "this case study")
    map_cache_path = os.path.join(args.out_dir, "map_candidates.json")
    topic_cache_path = os.path.join(args.out_dir, "topic_content.json")
    map_cache = load_json_cache(map_cache_path)
    topic_cache = load_json_cache(topic_cache_path)

    skipped_no_content = []

    for entry in manifest["readings"]:
        reading_id = entry["id"]
        reading = readings_by_id.get(reading_id, {})
        topics = reading.get("topics") or []
        if not topics:
            continue

        print(f"\n{reading_id} ({len(topics)} topics: {', '.join(topics)})")
        candidates, used_abstract = run_map_phase(
            reading_id, reading, entry, map_cache, map_backend, anthropic_client, map_model,
            args.force_map,
        )
        save_json_cache(map_cache_path, map_cache)

        if candidates is None:
            print("  no PDF text and no abstract -- skipping all topics for this reading")
            skipped_no_content.append(reading_id)
            entry["topics_extracted"] = []
            continue
        if used_abstract:
            print("  no PDF text available -- reducing from abstract only")

        extracted = []
        for topic_id in topics:
            result = run_reduce_phase(
                reading_id, reading, topic_id, topics_by_id, cs_name, candidates,
                topic_cache, reduce_backend, anthropic_client, reduce_model, args.force_reduce,
            )
            if result.get("key_facts"):
                extracted.append(topic_id)
            save_json_cache(topic_cache_path, topic_cache)

        entry["topics_extracted"] = extracted

    manifest_path = os.path.join(args.out_dir, "access_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. topic_content.json: {topic_cache_path}")
    if skipped_no_content:
        print(f"Skipped (no text or abstract available): {', '.join(skipped_no_content)}")


if __name__ == "__main__":
    main()
