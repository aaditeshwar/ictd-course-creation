"""
Score Tier B area-agnostic readings against case studies via nested-chunked LLM calls.

Only Tier B readings (area_agnostic, not in area_agnostic_topic_vector) are scored. Results are
cached incrementally to data/area_agnostic_relevance_scores.json. Does NOT modify
examples.json — use apply_area_agnostic_threshold.py for that.

Run:
    python skills/score_area_agnostic_relevance.py --dry-run
    python skills/score_area_agnostic_relevance.py --topic problem_discovery --backend ollama
    python skills/score_area_agnostic_relevance.py --backend ollama
"""
import argparse
import json
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
if str(_SKILLS.parent / "src") not in sys.path:
    sys.path.insert(0, str(_SKILLS.parent / "src"))

import anthropic

from area_agnostic_common import (
    CASE_STUDY_CHUNK_SIZE,
    DEFAULT_EXAMPLES,
    DEFAULT_FRAMEWORK,
    DEFAULT_READINGS,
    DEFAULT_SCORES_PATH,
    READING_CHUNK_SIZE,
    case_studies_for_topic,
    chunk_key_matches,
    chunk_list,
    chunk_pair_count,
    current_vector_reading_ids,
    load_examples,
    load_framework,
    load_json,
    load_readings,
    purge_tier_a_from_scores,
    readings_for_topic,
    split_tiers,
    tier_b_for_scoring,
    topic_ids,
)
from pipeline_common import get_anthropic_model, load_dotenv, require_anthropic_key
from llm_config import get_ollama_model
from ollama_client import ollama_generate, extract_json_object

SCORE_MAX_TOKENS = 8192
KEY_FACTS_SAMPLE = 3
ABSTRACT_SNIPPET = 200
CHARS_PER_TOKEN = 4
QWEN_CONTEXT_TOKENS = 32768

SCORE_PROMPT = """You are scoring how relevant area-agnostic academic readings are to EXISTING \
ICTD course case studies, for one shared topic: {topic_name} ({topic_id}).

Score EVERY (reading, case_study) pair listed below on a 1-5 scale:
  1 = no meaningful connection for this topic
  2 = very weak / tangential
  3 = moderate thematic overlap
  4 = strong fit — reading would usefully illustrate this case study for the topic
  5 = excellent fit — reading is a natural companion for teaching this case study on this topic

Most pairs will score 1-2. Score honestly; do not omit low-scoring pairs.

READINGS:
{readings_block}

CASE STUDIES:
{case_studies_block}

Respond with ONLY a JSON object in this exact shape:
{{"scores": [
  {{"reading_id": "<id>", "case_study_id": "<id>", "relevance_score": 1,
    "relevant_topic": "{topic_id}", "relevance_note": "one specific sentence"}},
  ...
]}}
Include one entry for EVERY reading x case_study combination above ({expected_cells} entries).
"""


def load_topic_content_cache():
    """Best-effort index: (case_study_id, reading_id, topic_id) -> key_facts list."""
    cache = {}
    prep_root = Path(__file__).resolve().parent.parent / "data" / "lecture-prep"
    if not prep_root.is_dir():
        return cache

    slug_to_case_study = {}
    index_path = prep_root / "index.json"
    if index_path.is_file():
        try:
            index = load_json(index_path)
            for case_study_id, entry in index.items():
                out_dir = entry.get("out_dir") or ""
                slug = Path(out_dir).name if out_dir else entry.get("slug")
                if slug:
                    slug_to_case_study[slug] = case_study_id
        except (OSError, json.JSONDecodeError):
            pass

    for topic_content_path in prep_root.glob("*/topic_content.json"):
        dir_name = topic_content_path.parent.name
        case_study_id = slug_to_case_study.get(dir_name, dir_name)
        try:
            data = load_json(topic_content_path)
        except (OSError, json.JSONDecodeError):
            continue
        for key, entry in data.items():
            if "::" not in key:
                continue
            rid, topic_id = key.split("::", 1)
            facts = entry.get("key_facts") or []
            if facts:
                cache[(case_study_id, rid, topic_id)] = facts
    return cache


def reading_block(readings):
    lines = []
    for r in readings:
        abstract = (r.get("abstract") or "(no abstract)")[:1500]
        lines.append(
            f"- id: {r['id']}\n  title: {r.get('title', '')}\n  abstract: {abstract}"
        )
    return "\n\n".join(lines)


def sample_key_facts(case_study, topic_id, readings_by_id, topic_content_cache):
    facts = []
    for rid in case_study.get("readings") or []:
        r = readings_by_id.get(rid)
        if not r or topic_id not in (r.get("topics") or []):
            continue
        cached = topic_content_cache.get((case_study["id"], rid, topic_id))
        if cached:
            facts.extend(cached[:KEY_FACTS_SAMPLE])
        elif r.get("abstract"):
            facts.append(f"{rid}: {(r['abstract'] or '')[:ABSTRACT_SNIPPET]}")
        if len(facts) >= KEY_FACTS_SAMPLE * 2:
            break
    return facts[:KEY_FACTS_SAMPLE * 2]


def case_study_block(case_studies, topic_id, readings_by_id, topic_content_cache):
    lines = []
    for cs in case_studies:
        facts = sample_key_facts(cs, topic_id, readings_by_id, topic_content_cache)
        facts_text = "\n    ".join(facts) if facts else "(no grounded key_facts available)"
        desc = (cs.get("description") or "")[:800]
        lines.append(
            f"- id: {cs['id']}\n  name: {cs.get('name', '')}\n  description: {desc}\n"
            f"  sample_key_facts_for_{topic_id}:\n    {facts_text}"
        )
    return "\n\n".join(lines)


def call_llm(prompt, backend, anthropic_client, max_tokens):
    if backend == "ollama":
        return ollama_generate(prompt, model=get_ollama_model(), num_predict=max_tokens)
    response = anthropic_client.messages.create(
        model=get_anthropic_model(),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def parse_scores(raw, reading_ids, case_study_ids, topic_id):
    parsed = extract_json_object(raw)
    if not isinstance(parsed, dict):
        return [], f"JSON parse failed: {raw[:200]!r}"

    expected = set((rid, csid) for rid in reading_ids for csid in case_study_ids)
    scores = parsed.get("scores") or []
    out = []
    seen = set()
    warnings = []

    for item in scores:
        if not isinstance(item, dict):
            continue
        rid = item.get("reading_id")
        csid = item.get("case_study_id")
        if (rid, csid) not in expected:
            warnings.append(f"unexpected pair ignored: {rid} x {csid}")
            continue
        if (rid, csid) in seen:
            warnings.append(f"duplicate pair ignored: {rid} x {csid}")
            continue
        seen.add((rid, csid))
        try:
            score = int(item.get("relevance_score"))
        except (TypeError, ValueError):
            warnings.append(f"invalid score for {rid} x {csid}")
            continue
        score = max(1, min(5, score))
        out.append({
            "reading_id": rid,
            "case_study_id": csid,
            "relevance_score": score,
            "relevant_topic": item.get("relevant_topic") or topic_id,
            "relevance_note": (item.get("relevance_note") or "").strip(),
        })

    missing = expected - seen
    if missing:
        warnings.append(f"{len(missing)} pairs missing from model output")
    return out, "; ".join(warnings) if warnings else ""


def load_scores_file(path):
    if not path.exists():
        return {"metadata": {}, "completed_chunks": [], "scores": []}
    return load_json(path)


def save_scores_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def chunk_already_done(completed_chunks, topic_id, reading_ids, case_study_ids, backend, model, scores=None):
    if scores is not None and all_pairs_scored(scores, topic_id, reading_ids, case_study_ids):
        return True
    for stored in completed_chunks:
        if not chunk_key_matches(stored, topic_id, reading_ids, case_study_ids, backend, model):
            continue
        if stored.get("cells_returned", 0) >= stored.get("cells_expected", 0):
            return True
    return False


def pairs_for_chunk(topic_id, reading_ids, case_study_ids):
    return {(topic_id, rid, csid) for rid in reading_ids for csid in case_study_ids}


def all_pairs_scored(scores, topic_id, reading_ids, case_study_ids):
    needed = pairs_for_chunk(topic_id, reading_ids, case_study_ids)
    have = {
        (s.get("topic"), s.get("reading_id"), s.get("case_study_id"))
        for s in scores
    }
    return needed.issubset(have)


def list_incomplete_chunks(completed_chunks):
    return [
        c for c in completed_chunks
        if c.get("cells_returned", 0) < c.get("cells_expected", 0)
    ]


def purge_chunk_scores(scores_data, topic_id, reading_ids, case_study_ids):
    pairs = pairs_for_chunk(topic_id, reading_ids, case_study_ids)
    scores_data["scores"] = [
        s for s in scores_data["scores"]
        if (s.get("topic"), s.get("reading_id"), s.get("case_study_id")) not in pairs
    ]


def remove_matching_chunks(completed_chunks, topic_id, reading_ids, case_study_ids, backend, model):
    return [
        c for c in completed_chunks
        if not chunk_key_matches(c, topic_id, reading_ids, case_study_ids, backend, model)
    ]


def score_one_chunk(
    scores_data,
    scores_path,
    topic_entry,
    topic_id,
    r_chunk,
    cs_chunk,
    readings_by_id,
    topic_content_cache,
    backend,
    model,
    anthropic_client,
    vector_ids,
    label,
):
    r_chunk = [r for r in r_chunk if r["id"] not in vector_ids]
    if not r_chunk:
        return 0, 0
    r_ids = [r["id"] for r in r_chunk]
    cs_ids = [cs["id"] for cs in cs_chunk]
    if any(rid in vector_ids for rid in r_ids):
        raise RuntimeError(f"Tier A reading in chunk: {[rid for rid in r_ids if rid in vector_ids]}")
    if chunk_already_done(
        scores_data["completed_chunks"], topic_id, r_ids, cs_ids, backend, model,
        scores=scores_data["scores"],
    ):
        print(f"  {label} — cached, skip")
        return 0, 0

    expected_cells = len(r_chunk) * len(cs_chunk)
    stale = find_incomplete_chunk(
        scores_data["completed_chunks"], topic_id, r_ids, cs_ids, backend, model
    )
    if stale:
        purge_chunk_scores(scores_data, topic_id, r_ids, cs_ids)
        scores_data["completed_chunks"] = remove_matching_chunks(
            scores_data["completed_chunks"], topic_id, r_ids, cs_ids, backend, model
        )
        print(
            f"  {label} — retry incomplete "
            f"({stale.get('cells_returned')}/{stale.get('cells_expected')})"
        )

    prompt = build_chunk_prompt(
        topic_entry, topic_id, r_chunk, cs_chunk,
        readings_by_id, topic_content_cache,
    )
    print(f"  {label} ({len(r_chunk)} readings x {len(cs_chunk)} case studies)...")
    raw = call_llm(prompt, backend, anthropic_client, SCORE_MAX_TOKENS)
    parsed_scores, warn = parse_scores(raw, r_ids, cs_ids, topic_id)
    if warn:
        print(f"    WARNING: {warn}")
    parsed_scores = [s for s in parsed_scores if s.get("reading_id") not in vector_ids]
    for item in parsed_scores:
        item["topic"] = topic_id
    scores_data["scores"].extend(parsed_scores)
    scores_data["completed_chunks"].append({
        "topic": topic_id,
        "reading_ids": r_ids,
        "case_study_ids": cs_ids,
        "backend": backend,
        "model": model,
        "cells_returned": len(parsed_scores),
        "cells_expected": expected_cells,
    })
    save_scores_file(scores_path, scores_data)
    print(f"    recorded {len(parsed_scores)}/{expected_cells} scores")
    return 1, len(parsed_scores)


def find_incomplete_chunk(completed_chunks, topic_id, reading_ids, case_study_ids, backend, model):
    for stored in completed_chunks:
        if chunk_key_matches(stored, topic_id, reading_ids, case_study_ids, backend, model):
            if stored.get("cells_returned", 0) < stored.get("cells_expected", 0):
                return stored
    return None


def estimate_tokens(text):
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_output_tokens(n_readings, n_case_studies):
    """Rough JSON output size: one scored pair ~180 chars."""
    return estimate_tokens("x" * (n_readings * n_case_studies * 180))


def build_chunk_prompt(topic_entry, topic_id, r_chunk, cs_chunk, readings_by_id, topic_content_cache):
    return SCORE_PROMPT.format(
        topic_name=topic_entry["name"],
        topic_id=topic_id,
        readings_block=reading_block(r_chunk),
        case_studies_block=case_study_block(
            cs_chunk, topic_id, readings_by_id, topic_content_cache
        ),
        expected_cells=len(r_chunk) * len(cs_chunk),
    )


def print_plan(framework, tier_b, case_studies, topics_filter=None,
               reading_chunk_size=READING_CHUNK_SIZE, case_study_chunk_size=CASE_STUDY_CHUNK_SIZE):
    topics = topics_filter or topic_ids(framework)
    vector_ids = current_vector_reading_ids(framework)
    print(f"Tier B readings (for example mapping): {len(tier_b)}")
    print(f"Tier A vector readings excluded from scoring: {len(vector_ids)}")
    print(f"Chunk sizes: {reading_chunk_size} readings x {case_study_chunk_size} case studies")
    print(f"{'Topic':<24} {'Readings':>8} {'Case studies':>12} {'Chunk pairs':>12}")
    print("-" * 60)
    total = 0
    for topic_id in topics:
        topic_entry = next(t for t in framework["topics"] if t["id"] == topic_id)
        rs = readings_for_topic(tier_b, topic_id)
        css = case_studies_for_topic(case_studies, topic_id)
        pairs = chunk_pair_count(len(rs), len(css), reading_chunk_size, case_study_chunk_size)
        total += pairs
        print(f"{topic_entry['name'][:24]:<24} {len(rs):>8} {len(css):>12} {pairs:>12}")
    print("-" * 60)
    print(f"{'Total LLM calls':<24} {'':>8} {'':>12} {total:>12}")


def print_prompt_length_summary(framework, tier_b, case_studies, topics_filter,
                                reading_chunk_size, case_study_chunk_size, readings_by_id,
                                topic_content_cache, backend, model):
    topics = topics_filter or topic_ids(framework)
    rows = []
    for topic_id in topics:
        topic_entry = next(t for t in framework["topics"] if t["id"] == topic_id)
        rs = readings_for_topic(tier_b, topic_id)
        css = case_studies_for_topic(case_studies, topic_id)
        if not rs or not css:
            continue
        for r_chunk in chunk_list(rs, reading_chunk_size):
            for cs_chunk in chunk_list(css, case_study_chunk_size):
                prompt = build_chunk_prompt(
                    topic_entry, topic_id, r_chunk, cs_chunk,
                    readings_by_id, topic_content_cache,
                )
                in_tok = estimate_tokens(prompt)
                out_tok = estimate_output_tokens(len(r_chunk), len(cs_chunk))
                rb = reading_block(r_chunk)
                csb = case_study_block(cs_chunk, topic_id, readings_by_id, topic_content_cache)
                rows.append({
                    "topic": topic_id,
                    "readings": len(r_chunk),
                    "case_studies": len(cs_chunk),
                    "cells": len(r_chunk) * len(cs_chunk),
                    "input_tokens": in_tok,
                    "output_tokens_est": out_tok,
                    "readings_chars": len(rb),
                    "cs_chars": len(csb),
                })

    if not rows:
        print("\nNo prompt-length stats (no topic has both readings and case studies).")
        return

    in_tokens = sorted(r["input_tokens"] for r in rows)
    out_tokens = sorted(r["output_tokens_est"] for r in rows)
    p95_idx = max(0, int(len(in_tokens) * 0.95) - 1)
    worst = max(rows, key=lambda r: r["input_tokens"])

    print(f"\nPrompt length estimate (backend={backend}, model={model})")
    print(f"  Input tokens  — min {in_tokens[0]:,} | median {in_tokens[len(in_tokens)//2]:,} | "
          f"p95 {in_tokens[p95_idx]:,} | max {in_tokens[-1]:,}")
    print(f"  Output est    — min {out_tokens[0]:,} | median {out_tokens[len(out_tokens)//2]:,} | "
          f"max {out_tokens[-1]:,} (num_predict cap={SCORE_MAX_TOKENS:,})")
    print(f"  Chunks over output cap: "
          f"{sum(1 for r in rows if r['output_tokens_est'] > SCORE_MAX_TOKENS)} / {len(rows)}")
    if backend == "ollama":
        print(f"  Chunks over qwen context (~{QWEN_CONTEXT_TOKENS:,}): "
              f"{sum(1 for r in rows if r['input_tokens'] > QWEN_CONTEXT_TOKENS)} / {len(rows)}")
    print(f"  Worst chunk: {worst['topic']} ({worst['readings']}r x {worst['case_studies']}cs, "
          f"{worst['cells']} cells) — in {worst['input_tokens']:,} tok | "
          f"readings {worst['readings_chars']:,}c + case studies {worst['cs_chars']:,}c | "
          f"out ~{worst['output_tokens_est']:,} tok")

    print("\n  Per-topic worst input chunk:")
    for topic_id in topics:
        topic_rows = [r for r in rows if r["topic"] == topic_id]
        if not topic_rows:
            continue
        tw = max(topic_rows, key=lambda r: r["input_tokens"])
        calls = chunk_pair_count(
            len(readings_for_topic(tier_b, topic_id)),
            len(case_studies_for_topic(case_studies, topic_id)),
            reading_chunk_size,
            case_study_chunk_size,
        )
        print(f"    {topic_id:<26} {calls:>4} calls | worst {tw['readings']}r x {tw['case_studies']}cs | "
              f"in {tw['input_tokens']:,} | out ~{tw['output_tokens_est']:,}")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK))
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    parser.add_argument("--scores", default=str(DEFAULT_SCORES_PATH))
    parser.add_argument("--topic", action="append", dest="topics",
                        help="Limit to one or more topic ids (repeatable)")
    parser.add_argument("--backend", default=None, choices=["ollama", "anthropic"])
    parser.add_argument("--reading-chunk-size", type=int, default=READING_CHUNK_SIZE)
    parser.add_argument("--case-study-chunk-size", type=int, default=CASE_STUDY_CHUNK_SIZE)
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; no LLM calls")
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="Re-score only incomplete cached chunks (use with smaller --reading-chunk-size / --case-study-chunk-size)",
    )
    args = parser.parse_args()

    from pipeline_common import get_alignment_backend
    backend = args.backend or get_alignment_backend() or "ollama"
    model = get_ollama_model() if backend == "ollama" else get_anthropic_model()

    framework = load_framework(args.framework)
    readings = load_readings(args.readings)
    case_studies, _ = load_examples(args.examples)
    readings_by_id = {r["id"]: r for r in readings}
    tier_b = tier_b_for_scoring(readings, framework)
    vector_ids = current_vector_reading_ids(framework)

    topics_to_run = args.topics or topic_ids(framework)
    for tid in topics_to_run:
        if tid not in topic_ids(framework):
            parser.error(f"Unknown topic: {tid}")

    print_plan(
        framework, tier_b, case_studies, topics_to_run,
        args.reading_chunk_size, args.case_study_chunk_size,
    )
    topic_content_cache = load_topic_content_cache()
    if args.dry_run:
        print_prompt_length_summary(
            framework, tier_b, case_studies, topics_to_run,
            args.reading_chunk_size, args.case_study_chunk_size,
            readings_by_id, topic_content_cache, backend, model,
        )
        print("\nDry run — no LLM calls.")
        return

    scores_path = Path(args.scores)
    scores_data = load_scores_file(scores_path)
    scores_data, removed_scores, removed_chunks = purge_tier_a_from_scores(scores_data, framework)
    if removed_scores or removed_chunks:
        save_scores_file(scores_path, scores_data)
        print(f"Purged Tier A vector scores: {removed_scores} score(s), {removed_chunks} chunk(s) removed")
    scores_data.setdefault("metadata", {})
    scores_data["metadata"].update({
        "backend": backend,
        "model": model,
        "reading_chunk_size": args.reading_chunk_size,
        "case_study_chunk_size": args.case_study_chunk_size,
    })
    anthropic_client = None
    if backend == "anthropic":
        require_anthropic_key()
        anthropic_client = anthropic.Anthropic()

    total_calls = 0
    total_scores_added = 0

    if args.retry_incomplete:
        incomplete = list_incomplete_chunks(scores_data["completed_chunks"])
        if not incomplete:
            print("\nNo incomplete chunks to retry.")
        else:
            print(f"\nRetrying {len(incomplete)} incomplete chunk(s) at "
                  f"{args.reading_chunk_size}x{args.case_study_chunk_size} sub-chunk size")
            for block in incomplete:
                topic_id = block["topic"]
                if args.topics and topic_id not in args.topics:
                    continue
                topic_entry = next(t for t in framework["topics"] if t["id"] == topic_id)
                r_ids = block["reading_ids"]
                cs_ids = block["case_study_ids"]
                print(
                    f"\n[{topic_id}] refill {len(r_ids)} readings x {len(cs_ids)} case studies "
                    f"({block.get('cells_returned')}/{block.get('cells_expected')} cells previously)"
                )
                purge_chunk_scores(scores_data, topic_id, r_ids, cs_ids)
                scores_data["completed_chunks"] = remove_matching_chunks(
                    scores_data["completed_chunks"], topic_id, r_ids, cs_ids, backend, model
                )
                save_scores_file(scores_path, scores_data)

                r_objs = [readings_by_id[rid] for rid in r_ids if rid in readings_by_id]
                cs_objs = [cs for cs in case_studies if cs["id"] in cs_ids]
                cs_objs.sort(key=lambda cs: cs_ids.index(cs["id"]))
                reading_subchunks = chunk_list(r_objs, args.reading_chunk_size)
                cs_subchunks = chunk_list(cs_objs, args.case_study_chunk_size)
                for ri, r_chunk in enumerate(reading_subchunks, start=1):
                    for ci, cs_chunk in enumerate(cs_subchunks, start=1):
                        label = f"sub-chunk {ri}/{len(reading_subchunks)} x {ci}/{len(cs_subchunks)}"
                        calls, added = score_one_chunk(
                            scores_data, scores_path, topic_entry, topic_id,
                            r_chunk, cs_chunk, readings_by_id, topic_content_cache,
                            backend, model, anthropic_client, vector_ids, label,
                        )
                        total_calls += calls
                        total_scores_added += added

                if all_pairs_scored(scores_data["scores"], topic_id, r_ids, cs_ids):
                    scores_data["completed_chunks"].append({
                        "topic": topic_id,
                        "reading_ids": r_ids,
                        "case_study_ids": cs_ids,
                        "backend": backend,
                        "model": model,
                        "cells_returned": len(r_ids) * len(cs_ids),
                        "cells_expected": len(r_ids) * len(cs_ids),
                    })
                    save_scores_file(scores_path, scores_data)
                    print(f"  region complete — all {len(r_ids) * len(cs_ids)} pairs scored")
                else:
                    missing = len(r_ids) * len(cs_ids) - sum(
                        1 for s in scores_data["scores"]
                        if s.get("topic") == topic_id
                        and s.get("reading_id") in r_ids
                        and s.get("case_study_id") in cs_ids
                    )
                    print(f"  region still incomplete — {missing} pair(s) missing")
    else:
        for topic_id in topics_to_run:
            topic_entry = next(t for t in framework["topics"] if t["id"] == topic_id)
            topic_readings = readings_for_topic(tier_b, topic_id)
            topic_cs = case_studies_for_topic(case_studies, topic_id)
            if not topic_readings or not topic_cs:
                print(f"\n[{topic_id}] skipped — readings={len(topic_readings)}, case_studies={len(topic_cs)}")
                continue

            print(f"\n[{topic_id}] {len(topic_readings)} readings x {len(topic_cs)} case studies")
            reading_chunks = chunk_list(topic_readings, args.reading_chunk_size)
            cs_chunks = chunk_list(topic_cs, args.case_study_chunk_size)

            for ri, r_chunk in enumerate(reading_chunks, start=1):
                for ci, cs_chunk in enumerate(cs_chunks, start=1):
                    label = f"chunk {ri}/{len(reading_chunks)} x {ci}/{len(cs_chunks)}"
                    calls, added = score_one_chunk(
                        scores_data, scores_path, topic_entry, topic_id,
                        r_chunk, cs_chunk, readings_by_id, topic_content_cache,
                        backend, model, anthropic_client, vector_ids, label,
                    )
                    total_calls += calls
                    total_scores_added += added

    print(f"\nDone. {total_calls} new chunk pair(s), {total_scores_added} score(s) added.")
    print(f"Total scores in file: {len(scores_data['scores'])}")
    print(f"Written to {scores_path}")


if __name__ == "__main__":
    main()
