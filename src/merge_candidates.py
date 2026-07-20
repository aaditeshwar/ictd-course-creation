"""
After reviewing candidates_<venue>.json by hand (deleting/editing entries you disagree with,
filling in the "id" field with a slug like "kdd24_papername_shortauthor"), run:

    python merge_candidates.py candidates_kdd_2024_reviewed.json ../readings.json

This appends the approved entries into readings.json, re-runs the dedup check against the
FULL updated corpus (not just pre-existing readings, to catch collisions between candidate
files from different venues), and updates readings_list_metadata.
"""
import sys
import json
import re
from dedup import build_existing_sigs, find_best_match, sig_words


def merge(candidates_path, readings_path="data/readings.json"):
    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)
    with open(readings_path, encoding="utf-8") as f:
        rd = json.load(f)

    existing_ids = {r["id"] for r in rd["readings"]}
    existing_sigs = build_existing_sigs(rd["readings"])

    added, skipped = 0, 0
    for c in candidates:
        c.pop("_matched_keywords", None)  # QA-only field, don't persist it

        if not c.get("id"):
            # auto-generate a slug if the reviewer didn't set one
            slug = re.sub(r"[^a-z0-9]+", "_", c["title"].lower()).strip("_")
            c["id"] = f"{c.get('venue', 'venue')}_{'_'.join(slug.split('_')[:6])}"

        if c["id"] in existing_ids:
            print(f"SKIP (id collision): {c['id']}")
            skipped += 1
            continue

        match, score = find_best_match(c["title"], existing_sigs)
        if match and score >= 0.65:
            print(f"SKIP (duplicate of {match['id']}, score={score:.2f}): {c['title'][:70]}")
            skipped += 1
            continue

        rd["readings"].append(c)
        existing_ids.add(c["id"])
        existing_sigs.append((c, sig_words(c["title"])))
        added += 1

    venue_name = candidates[0].get("venue", "unknown_venue") if candidates else "unknown_venue"
    rd["readings_list_metadata"].setdefault("source_courses", {})[f"{venue_name}_venue_search"] = (
        f"Papers merged from local pipeline run on {venue_name}, reviewed by instructor before merge."
    )
    rd["readings_list_metadata"]["count"] = len(rd["readings"])

    with open(readings_path, "w", encoding="utf-8") as f:
        json.dump(rd, f, indent=2)

    print(f"Merged {added} readings, skipped {skipped}. New total: {len(rd['readings'])}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    merge(sys.argv[1], sys.argv[2])
