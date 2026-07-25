"""
Apply threshold to cached area-agnostic relevance scores and write Tier B links
onto case studies in examples.json.

Adds/updates related_area_agnostic_readings only — does NOT modify readings[] or
topics_covered/cross_cutting_axes. Tier A vector changes are handled separately by
rebuild_area_agnostic_vector.py.

Run:
    python skills/apply_area_agnostic_threshold.py --dry-run --min-score 4 --max-case-studies-per-reading 3
    python skills/apply_area_agnostic_threshold.py --write --min-score 4 --max-case-studies-per-reading 3
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

from area_agnostic_common import (
    DEFAULT_EXAMPLES,
    DEFAULT_FRAMEWORK,
    DEFAULT_READINGS,
    DEFAULT_SCORES_PATH,
    current_vector_reading_ids,
    load_framework,
    load_json,
    purge_tier_a_from_scores,
)

DEFAULT_GE4_GE5_CSV = Path(__file__).resolve().parent.parent / "data" / "ge4_ge5_paper_mapping.csv"


def load_examples(path):
    return load_json(path)


def apply_threshold(scores, min_score, max_per_reading):
    """Return case_study_id -> list of link dicts, and tie_break flags."""
    by_reading = defaultdict(list)
    for row in scores:
        if row.get("relevance_score", 0) < min_score:
            continue
        by_reading[row["reading_id"]].append(row)

    case_study_links = defaultdict(list)
    tie_breaks = []

    for reading_id, rows in by_reading.items():
        rows_sorted = sorted(
            rows,
            key=lambda r: (-r["relevance_score"], r["case_study_id"], r.get("relevance_note", "")),
        )
        if max_per_reading and len(rows_sorted) > max_per_reading:
            cutoff_score = rows_sorted[max_per_reading - 1]["relevance_score"]
            tied = [r for r in rows_sorted if r["relevance_score"] == cutoff_score]
            if len(tied) > 1:
                tie_breaks.append({
                    "reading_id": reading_id,
                    "score": cutoff_score,
                    "tied_case_studies": [r["case_study_id"] for r in tied],
                })
        selected = rows_sorted if not max_per_reading else rows_sorted[:max_per_reading]
        for row in selected:
            link = {
                "reading_id": row["reading_id"],
                "relevant_topic": row.get("relevant_topic") or row.get("topic"),
                "relevance_score": row["relevance_score"],
                "relevance_note": row.get("relevance_note", ""),
            }
            case_study_links[row["case_study_id"]].append(link)

    for cs_id in case_study_links:
        case_study_links[cs_id].sort(
            key=lambda x: (-x["relevance_score"], x["reading_id"])
        )
    return case_study_links, tie_breaks


def export_ge4_ge5_csv(scores, readings_by_id, csv_path):
    """Write reading_id, title, case_studies_ge5, case_studies_ge4 for papers with >=1 ge4 match."""
    ge4 = defaultdict(set)
    ge5 = defaultdict(set)
    for row in scores:
        rid = row["reading_id"]
        csid = row["case_study_id"]
        score = row.get("relevance_score", 0)
        if score >= 4:
            ge4[rid].add(csid)
        if score >= 5:
            ge5[rid].add(csid)

    rows = []
    for rid in ge4:
        reading = readings_by_id.get(rid, {})
        rows.append({
            "reading_id": rid,
            "title": reading.get("title") or rid,
            "case_studies_ge5": len(ge5.get(rid, set())),
            "case_studies_ge4": len(ge4[rid]),
        })
    rows.sort(key=lambda r: (-r["case_studies_ge4"], -r["case_studies_ge5"], r["reading_id"]))

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["reading_id", "title", "case_studies_ge5", "case_studies_ge4"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def clear_related_links(case_studies):
    for cs in case_studies:
        cs["related_area_agnostic_readings"] = []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK))
    parser.add_argument("--scores", default=str(DEFAULT_SCORES_PATH))
    parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument(
        "--max-case-studies-per-reading",
        type=int,
        default=0,
        help="Cap links per reading (0 = no cap, include all qualifying case studies)",
    )
    parser.add_argument("--export-csv", default=str(DEFAULT_GE4_GE5_CSV),
                        help="Write ge4/ge5 paper mapping CSV (default: data/ge4_ge5_paper_mapping.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write (default)")
    parser.add_argument("--write", action="store_true", help="Write updated examples.json")
    args = parser.parse_args()

    if args.write and args.dry_run:
        parser.error("Use either --dry-run or --write, not both.")
    if args.min_score < 1 or args.min_score > 5:
        parser.error("--min-score must be between 1 and 5")

    scores_path = Path(args.scores)
    if not scores_path.exists():
        parser.error(f"Scores file not found: {scores_path}. Run score_area_agnostic_relevance.py first.")

    scores_data = load_json(scores_path)
    framework = load_framework(args.framework)
    scores_data, _, _ = purge_tier_a_from_scores(scores_data, framework)
    scores = scores_data.get("scores") or []
    readings_by_id = {
        r["id"]: r for r in load_json(DEFAULT_READINGS)["readings"]
    }
    examples_data = load_examples(args.examples)
    case_studies = examples_data.get("case_studies", [])

    max_per_reading = args.max_case_studies_per_reading or None
    case_study_links, tie_breaks = apply_threshold(
        scores, args.min_score, max_per_reading
    )

    csv_rows = export_ge4_ge5_csv(scores, readings_by_id, Path(args.export_csv))
    print(f"Exported {len(csv_rows)} paper(s) with >=4 to {args.export_csv}")

    total_links = sum(len(v) for v in case_study_links.values())
    readings_linked = len({link["reading_id"] for links in case_study_links.values() for link in links})
    qualifying_pairs = sum(1 for s in scores if s.get("relevance_score", 0) >= args.min_score)

    print(f"Scores file: {scores_path} ({len(scores)} cells)")
    cap_label = "none" if max_per_reading is None else str(max_per_reading)
    print(f"Threshold: min_score={args.min_score}, max_case_studies_per_reading={cap_label}")
    print(f"Qualifying pairs (before per-reading cap): {qualifying_pairs}")
    print(f"Links written to case studies: {total_links} across {len(case_study_links)} case studies")
    print(f"Distinct Tier B readings linked: {readings_linked}")

    if tie_breaks:
        print(f"\nTie-breaks at cap boundary: {len(tie_breaks)}")
        for tb in tie_breaks[:10]:
            print(f"  {tb['reading_id']} score={tb['score']}: kept first among {tb['tied_case_studies']}")
        if len(tie_breaks) > 10:
            print(f"  ... and {len(tie_breaks) - 10} more")

    top_cs = sorted(case_study_links.items(), key=lambda kv: -len(kv[1]))[:10]
    if top_cs:
        print("\nCase studies with most links:")
        for cs_id, links in top_cs:
            print(f"  {cs_id}: {len(links)} reading(s)")

    if not args.write:
        print("\nDry run — examples.json unchanged. Re-run with --write to apply.")
        return

    clear_related_links(case_studies)
    by_id = {cs["id"]: cs for cs in case_studies}
    for cs_id, links in case_study_links.items():
        cs = by_id.get(cs_id)
        if cs:
            cs["related_area_agnostic_readings"] = links

    examples_data.setdefault("metadata", {})["related_area_agnostic_note"] = (
        f"Tier B area-agnostic links from apply_area_agnostic_threshold.py "
        f"(min_score={args.min_score}, max_case_studies_per_reading={cap_label}). "
        f"Does not affect readings[] or topics_covered derivation."
    )

    with open(args.examples, "w", encoding="utf-8") as f:
        json.dump(examples_data, f, indent=2)
    print(f"\nWrote {args.examples}")


if __name__ == "__main__":
    main()
