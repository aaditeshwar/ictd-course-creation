"""
Assign newly merged readings to EXISTING case studies in examples.json — no domain
re-clustering and no new case studies.

Processes **one framework area at a time**: case studies and readings are filtered to the
current area, then readings are sent in chunks. Cross-area readings are considered in each
area pass until assigned.

Install: pip install anthropic requests  (anthropic only if --backend anthropic)

Run:
    python skills/assign_readings_to_examples.py --dry-run
    python skills/assign_readings_to_examples.py --dry-run --candidates data/candidates_cscw_2025_1.json
    python skills/assign_readings_to_examples.py --backend ollama --venue-prefix cscw_
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
_PROJECT = _SKILLS.parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
if str(_PROJECT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT / "src"))

from pipeline_common import load_dotenv, get_anthropic_model
from llm_config import get_ollama_model
from ollama_client import ollama_generate, extract_json_object

DEFAULT_FRAMEWORK = "data/framework.json"
DEFAULT_READINGS = "data/readings.json"
DEFAULT_EXAMPLES = "data/examples.json"
DEFAULT_CHUNK_SIZE = 40
ASSIGN_MAX_TOKENS = 8192
CHARS_PER_TOKEN = 4

ASSIGN_PROMPT = """You are assigning academic readings to EXISTING case studies in an ICTD course.

A case study is a recurring real-world domain (e.g. "voice-based agricultural extension"), not a
single paper. Each reading must go to at most ONE existing case study — the best thematic fit.

RULES:
- Use ONLY case study ids from the existing list below. Do NOT propose new case studies.
- All readings and case studies in this batch belong to the "{area_name}" area ({area_id}).
- If no existing case study is a reasonable fit, leave that reading unassigned.
- Every reading id in the input chunk should appear in fold_into_existing or unassigned.

EXISTING CASE STUDIES ({area_id}):
{case_studies_block}

READINGS TO ASSIGN (not yet in any case study):
{readings_block}

Respond with ONLY a JSON object in this exact shape (no other keys):
{{"fold_into_existing": {{"<case_study_id>": ["<reading_id>", ...], ...}}, "unassigned": ["<reading_id>", ...]}}
"""


def chunk_list(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def load_examples(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("case_studies", []), data.get("metadata", {})


def load_readings(path):
    with open(path, encoding="utf-8") as f:
        return normalize_readings(json.load(f)["readings"])


def load_candidate_readings(path):
    """Pipeline candidates not yet merged into readings.json (for dry-run sizing)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("readings", [])
    return normalize_readings(items)


def synthetic_reading_id(reading):
    if reading.get("id"):
        return reading["id"]
    slug = re.sub(r"[^a-z0-9]+", "_", reading.get("title", "paper").lower()).strip("_")
    return f"{reading.get('venue', 'venue')}_{'_'.join(slug.split('_')[:6])}"


def normalize_readings(readings):
    """Ensure every reading has an id (candidates from pipeline may have id: null)."""
    out = []
    for r in readings:
        r = dict(r)
        if not r.get("id"):
            r["id"] = synthetic_reading_id(r)
        out.append(r)
    return out


def topic_order_ids(framework):
    return [t["id"] for t in sorted(framework["topics"], key=lambda t: t["sequence"])]


def framework_areas(framework):
    return framework["areas"]


def recompute_coverage(case_studies, readings_by_id, topic_order, axis_order):
    for cs in case_studies:
        topics, axes = set(), set()
        for rid in cs["readings"]:
            r = readings_by_id.get(rid)
            if r is None:
                continue
            topics.update(r.get("topics") or [])
            axes.update(r.get("cross_cutting_axes") or [])
        cs["topics_covered"] = [t for t in topic_order if t in topics]
        cs["cross_cutting_axes"] = [a for a in axis_order if a in axes]
    return case_studies


def covered_reading_ids(case_studies):
    return {rid for cs in case_studies for rid in cs.get("readings", [])}


def reading_matches_venue_prefix(reading, venue_prefix):
    if not venue_prefix:
        return True
    return (
        (reading.get("venue") or "").startswith(venue_prefix)
        or reading["id"].startswith(venue_prefix)
    )


def uncovered_for_area(readings, covered, area_id, venue_prefix=None):
    out = []
    for r in readings:
        if r.get("area_agnostic"):
            continue
        if area_id not in (r.get("areas") or []):
            continue
        if r["id"] in covered:
            continue
        if not reading_matches_venue_prefix(r, venue_prefix):
            continue
        out.append(r)
    return out


def case_studies_for_area(case_studies, area_id):
    return [cs for cs in case_studies if area_id in (cs.get("areas") or [])]


def format_case_studies_block(case_studies):
    lines = []
    for cs in case_studies:
        desc = (cs.get("description") or "")[:250].replace("\n", " ")
        lines.append(
            f"- {cs['id']}: {cs['name']} | areas={cs.get('areas', [])} | "
            f"topics_covered={cs.get('topics_covered', [])}\n  {desc}"
        )
    return "\n".join(lines) if lines else "(no case studies in this area)"


def format_readings_block(readings):
    if not readings:
        return "(none)"
    return "\n".join(
        f"- {r['id']} | {r['title'][:100]} | areas={r.get('areas', [])} | topics={r.get('topics', [])}"
        for r in readings
    )


def build_prompt(area_id, area_name, case_studies, chunk):
    return ASSIGN_PROMPT.format(
        area_id=area_id,
        area_name=area_name,
        case_studies_block=format_case_studies_block(case_studies),
        readings_block=format_readings_block(chunk),
    )


def estimate_tokens(char_count):
    return math.ceil(char_count / CHARS_PER_TOKEN)


def plan_area_batches(framework, readings, case_studies, venue_prefix, chunk_size):
    """Return per-area work plan with prompt size estimates for the largest chunk."""
    covered = covered_reading_ids(case_studies)
    plans = []
    for area in framework_areas(framework):
        area_id = area["id"]
        area_cs = case_studies_for_area(case_studies, area_id)
        area_uncovered = uncovered_for_area(readings, covered, area_id, venue_prefix)
        if not area_uncovered or not area_cs:
            plans.append({
                "area_id": area_id,
                "area_name": area["name"],
                "case_studies": len(area_cs),
                "readings": len(area_uncovered),
                "chunks": 0,
                "max_prompt_chars": 0,
                "max_prompt_tokens": 0,
            })
            continue
        chunks = chunk_list(area_uncovered, chunk_size)
        cs_block = format_case_studies_block(area_cs)
        max_chars = 0
        for chunk in chunks:
            prompt = build_prompt(area_id, area["name"], area_cs, chunk)
            max_chars = max(max_chars, len(prompt))
        plans.append({
            "area_id": area_id,
            "area_name": area["name"],
            "case_studies": len(area_cs),
            "readings": len(area_uncovered),
            "chunks": len(chunks),
            "max_prompt_chars": max_chars,
            "max_prompt_tokens": estimate_tokens(max_chars),
        })
    return plans


def print_dry_run(framework, readings, case_studies, venue_prefix, chunk_size, candidates_path=None):
    if candidates_path:
        extra = load_candidate_readings(candidates_path)
        print(f"Using {len(extra)} candidate reading(s) from {candidates_path} (not yet in readings.json)")
        readings = list(readings) + extra

    covered = covered_reading_ids(case_studies)
    total_uncovered = sum(
        len(uncovered_for_area(readings, covered, a["id"], venue_prefix))
        for a in framework_areas(framework)
    )
    # cross-area readings counted once per area in sum above — also report unique
    unique_uncovered = []
    seen = set()
    for area in framework_areas(framework):
        for r in uncovered_for_area(readings, covered, area["id"], venue_prefix):
            if r["id"] not in seen:
                seen.add(r["id"])
                unique_uncovered.append(r)

    print(f"Existing case studies: {len(case_studies)}")
    print(f"Uncovered readings (unique): {len(unique_uncovered)}"
          + (f" | venue/id prefix: {venue_prefix!r}" if venue_prefix else ""))
    print(f"Chunk size: {chunk_size} | ASSIGN_MAX_TOKENS (output): {ASSIGN_MAX_TOKENS}")
    print()

    plans = plan_area_batches(framework, readings, case_studies, venue_prefix, chunk_size)
    active = [p for p in plans if p["readings"] and p["case_studies"]]
    total_calls = sum(p["chunks"] for p in active)

    print(f"{'Area':<22} {'CS':>4} {'Rdgs':>5} {'Chunks':>7} {'Max prompt':>12} {'~tokens':>8}")
    print("-" * 65)
    for p in plans:
        if not p["readings"]:
            continue
        flag = " !" if p["max_prompt_tokens"] > 12000 else (" ?" if p["max_prompt_tokens"] > 8000 else "")
        print(
            f"{p['area_id']:<22} {p['case_studies']:>4} {p['readings']:>5} {p['chunks']:>7} "
            f"{p['max_prompt_chars']:>10,} {p['max_prompt_tokens']:>7,}{flag}"
        )
    print("-" * 65)
    print(f"Total LLM calls (areas with work): {total_calls}")
    if active:
        worst = max(active, key=lambda p: p["max_prompt_tokens"])
        print(f"Largest prompt: {worst['area_id']} ~{worst['max_prompt_tokens']:,} tokens "
              f"({worst['case_studies']} case studies, chunk up to {chunk_size} readings)")
    print()
    print("Legend: ! >12k est input tokens  ? >8k est input tokens")

    if unique_uncovered:
        print("\nSample uncovered readings:")
        for r in unique_uncovered[:30]:
            print(f"  {r['id']} | {r['title'][:75]} | areas={r.get('areas')}")
        if len(unique_uncovered) > 30:
            print(f"  ... and {len(unique_uncovered) - 30} more")


def call_llm(prompt, backend, anthropic_client, max_tokens):
    if backend == "ollama":
        return ollama_generate(prompt, model=get_ollama_model(), num_predict=max_tokens)
    response = anthropic_client.messages.create(
        model=get_anthropic_model(),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def parse_assignment_response(raw, valid_cs_ids, chunk_ids):
    parsed = extract_json_object(raw)
    if not isinstance(parsed, dict):
        return {}, set(chunk_ids), "JSON parse failed"

    fold = parsed.get("fold_into_existing") or {}
    unassigned = set(parsed.get("unassigned") or [])
    assigned_in_fold = set()

    assignments = {}
    warnings = []
    for cs_id, rids in fold.items():
        if cs_id not in valid_cs_ids:
            warnings.append(f"unknown case study id ignored: {cs_id}")
            continue
        good = []
        for rid in rids or []:
            if rid not in chunk_ids:
                warnings.append(f"unknown reading id in fold: {rid}")
                continue
            if rid in assigned_in_fold:
                warnings.append(f"duplicate assignment ignored: {rid}")
                continue
            good.append(rid)
            assigned_in_fold.add(rid)
        if good:
            assignments.setdefault(cs_id, []).extend(good)

    for rid in unassigned:
        if rid in chunk_ids:
            assigned_in_fold.add(rid)

    missing = chunk_ids - assigned_in_fold
    if missing:
        warnings.append(f"{len(missing)} readings neither folded nor listed unassigned")
    return assignments, missing, "; ".join(warnings) if warnings else ""


def apply_assignments(case_studies, fold_assignments):
    by_id = {cs["id"]: cs for cs in case_studies}
    added = 0
    for cs_id, rids in fold_assignments.items():
        cs = by_id.get(cs_id)
        if not cs:
            continue
        before = set(cs["readings"])
        cs["readings"] = sorted(before | set(rids))
        added += len(set(rids) - before)
    return added


def assign_area(area, readings, case_studies, covered, venue_prefix, chunk_size, backend, anthropic_client):
    area_id = area["id"]
    area_cs = case_studies_for_area(case_studies, area_id)
    area_uncovered = uncovered_for_area(readings, covered, area_id, venue_prefix)
    if not area_uncovered:
        return 0, 0, 0
    if not area_cs:
        print(f"  [{area_id}] {len(area_uncovered)} uncovered reading(s) but no case studies — skipping")
        return 0, len(area_uncovered), 0

    chunks = chunk_list(area_uncovered, chunk_size)
    print(f"  [{area_id}] {len(area_uncovered)} reading(s), {len(area_cs)} case study(ies), "
          f"{len(chunks)} chunk(s)")

    added_area = 0
    unassigned_area = 0
    valid_cs_ids = {cs["id"] for cs in area_cs}

    for i, chunk in enumerate(chunks, start=1):
        prompt = build_prompt(area_id, area["name"], area_cs, chunk)
        print(f"    chunk {i}/{len(chunks)} ({len(chunk)} readings, prompt ~{estimate_tokens(len(prompt)):,} tokens)...")
        raw = call_llm(prompt, backend, anthropic_client, ASSIGN_MAX_TOKENS)
        chunk_ids = {r["id"] for r in chunk}
        fold, missing, warn = parse_assignment_response(raw, valid_cs_ids, chunk_ids)
        if warn:
            print(f"      WARNING: {warn}")
        n = apply_assignments(case_studies, fold)
        added_area += n
        unassigned_area += len(missing)
        for rid in chunk_ids - missing:
            covered.add(rid)
        print(f"      assigned {n}; {len(missing)} unassigned this chunk")

    return added_area, unassigned_area, len(chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--framework", default=DEFAULT_FRAMEWORK)
    parser.add_argument("--readings", default=DEFAULT_READINGS)
    parser.add_argument("--examples", default=DEFAULT_EXAMPLES,
                        help="existing examples.json to update in place (--out defaults to same path)")
    parser.add_argument("--out", default=None, help="output path (default: overwrite --examples)")
    parser.add_argument("--backend", choices=("ollama", "anthropic"), default="ollama")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--venue-prefix", default=None,
                        help="only assign readings whose venue or id starts with this prefix (e.g. cscw_)")
    parser.add_argument("--candidates", default=None,
                        help="candidates_*.json for dry-run sizing before merge (not used in live assign)")
    parser.add_argument("--dry-run", action="store_true",
                        help="per-area prompt size estimates; no LLM calls")
    args = parser.parse_args()

    out_path = args.out or args.examples

    with open(args.framework, encoding="utf-8") as f:
        framework = json.load(f)
    readings = load_readings(args.readings)
    readings_by_id = {r["id"]: r for r in readings}
    case_studies, metadata = load_examples(args.examples)

    if args.dry_run:
        print_dry_run(framework, readings, case_studies, args.venue_prefix, args.chunk_size,
                        args.candidates)
        return

    covered = covered_reading_ids(case_studies)
    total_to_assign = len({
        r["id"]
        for area in framework_areas(framework)
        for r in uncovered_for_area(readings, covered, area["id"], args.venue_prefix)
    })
    if total_to_assign == 0:
        print("Nothing to assign.")
        return

    load_dotenv()
    anthropic_client = None
    if args.backend == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY not set (use --backend ollama or add key to .env)")
        import anthropic
        anthropic_client = anthropic.Anthropic()

    print(f"Backend: {args.backend} | processing area-by-area")
    total_added = 0
    total_unassigned = 0
    total_chunks = 0

    for area in framework_areas(framework):
        print(f"\nArea: {area['name']} ({area['id']})")
        added, unassigned, chunks = assign_area(
            area, readings, case_studies, covered, args.venue_prefix,
            args.chunk_size, args.backend, anthropic_client,
        )
        total_added += added
        total_unassigned += unassigned
        total_chunks += chunks

    topic_order = topic_order_ids(framework)
    axis_order = [a["id"] for a in framework["cross_cutting_axes"]]
    case_studies = recompute_coverage(case_studies, readings_by_id, topic_order, axis_order)

    covered_final = covered_reading_ids(case_studies)
    metadata = dict(metadata)
    metadata.update({
        "readings_referenced": len(covered_final),
        "readings_total_in_corpus": len(readings),
        "assignment_note": (
            f"Incremental area-by-area assignment via assign_readings_to_examples.py "
            f"({args.backend}); no new case studies created."
        ),
    })
    metadata["total_case_studies"] = len(case_studies)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"metadata": metadata, "case_studies": case_studies}, f, indent=2)

    print(f"\nDone. {total_chunks} chunk(s), {total_added} reading reference(s) added; "
          f"{total_unassigned} left unassigned.")
    print(f"Coverage: {len(covered_final)}/{len(readings)} readings in case studies.")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
