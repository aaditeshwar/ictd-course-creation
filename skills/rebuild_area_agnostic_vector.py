"""
Rebuild framework.json area_agnostic_topic_vector from Tier A readings (no LLM).

Tier A: area_agnostic readings with len(topics) >= 2 OR notes starting with
"This is a book. ".

Only updates area_agnostic_topic_vector in framework.json — does NOT touch examples.json.

Run:
    python skills/rebuild_area_agnostic_vector.py --dry-run
    python skills/rebuild_area_agnostic_vector.py --write
"""
import argparse
import copy
import json
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

from area_agnostic_common import (
    DEFAULT_DEMOTE_TO_TIER_B_IDS,
    DEFAULT_FRAMEWORK,
    DEFAULT_KEEP_READING_IDS,
    DEFAULT_READINGS,
    current_vector_reading_ids,
    is_book_reading,
    is_tier_a,
    load_framework,
    load_readings,
    rebuild_vector_membership,
    split_tiers,
    topic_ids,
)


def compute_diff(framework, new_by_topic):
    old_by_topic = {
        entry["id"]: list(entry.get("example_readings") or [])
        for entry in framework.get("area_agnostic_topic_vector", [])
    }
    all_topics = topic_ids(framework)

    added = {}
    removed = {}
    for topic_id in all_topics:
        old_set = set(old_by_topic.get(topic_id, []))
        new_set = set(new_by_topic.get(topic_id, []))
        topic_added = sorted(new_set - old_set)
        topic_removed = sorted(old_set - new_set)
        if topic_added:
            added[topic_id] = topic_added
        if topic_removed:
            removed[topic_id] = topic_removed

    old_all = current_vector_reading_ids(framework)
    new_all = {rid for ids in new_by_topic.values() for rid in ids}
    return added, removed, sorted(new_all - old_all), sorted(old_all - new_all)


def print_tier_summary(area_agnostic, tier_a, tier_b):
    print(f"Area-agnostic readings: {len(area_agnostic)}")
    print(f"  Tier A (vector candidates): {len(tier_a)}")
    print(f"  Tier B (example mapping):     {len(tier_b)}")
    print()
    print("Tier A readings:")
    for r in sorted(tier_a, key=lambda x: x["id"]):
        topics = r.get("topics") or []
        if is_book_reading(r):
            reason = f"book, topics={len(topics)}"
        else:
            reason = f"breadth={len(topics)}"
        print(f"  {r['id']} [{reason}] topics={topics}")


def print_diff(added, removed, added_global, removed_global):
    if added_global:
        print(f"\nNew reading ids in vector (global): {len(added_global)}")
        for rid in added_global[:20]:
            print(f"  + {rid}")
        if len(added_global) > 20:
            print(f"  ... and {len(added_global) - 20} more")

    if removed_global:
        print(f"\nReading ids falling OUT of vector under recomputed Tier A rule: {len(removed_global)}")
        for rid in removed_global:
            print(f"  - {rid}")

    for topic_id in sorted(set(list(added.keys()) + list(removed.keys()))):
        print(f"\nTopic: {topic_id}")
        if topic_id in added:
            print(f"  added ({len(added[topic_id])}): {', '.join(added[topic_id][:8])}"
                  + (f" ... +{len(added[topic_id]) - 8}" if len(added[topic_id]) > 8 else ""))
        if topic_id in removed:
            print(f"  removed ({len(removed[topic_id])}): {', '.join(removed[topic_id])}")


def apply_vector_update(framework, new_by_topic):
    updated = copy.deepcopy(framework)
    topic_set = set(new_by_topic.keys())
    for entry in updated.get("area_agnostic_topic_vector", []):
        topic_id = entry["id"]
        if topic_id in new_by_topic:
            entry["example_readings"] = new_by_topic[topic_id]
        else:
            entry["example_readings"] = []
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK))
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument("--dry-run", action="store_true", help="Report diff only; do not write (default)")
    parser.add_argument("--write", action="store_true", help="Write updated framework.json")
    parser.add_argument(
        "--keep",
        nargs="*",
        default=list(DEFAULT_KEEP_READING_IDS),
        metavar="READING_ID",
        help="Reading ids to retain in vector even if not Tier A (default: curated exceptions)",
    )
    parser.add_argument(
        "--demote",
        nargs="*",
        default=list(DEFAULT_DEMOTE_TO_TIER_B_IDS),
        metavar="READING_ID",
        help="Tier A readings to remove from vector and score as Tier B (default: curated demotions)",
    )
    args = parser.parse_args()

    if args.write and args.dry_run:
        parser.error("Use either --dry-run or --write, not both.")

    framework = load_framework(args.framework)
    readings = load_readings(args.readings)
    readings_by_id = {r["id"]: r for r in readings}
    keep_ids = list(dict.fromkeys(args.keep))
    demote_ids = list(dict.fromkeys(args.demote))
    area_agnostic, tier_a, tier_b = split_tiers(
        readings, framework, demote_to_tier_b_ids=demote_ids, keep_reading_ids=keep_ids
    )
    new_by_topic = rebuild_vector_membership(
        tier_a,
        framework,
        readings_by_id,
        keep_reading_ids=keep_ids,
        demote_to_tier_b_ids=demote_ids,
    )
    added, removed, added_global, removed_global = compute_diff(framework, new_by_topic)

    print_tier_summary(area_agnostic, tier_a, tier_b)
    if keep_ids:
        print(f"\nRetained by --keep ({len(keep_ids)}): {', '.join(keep_ids)}")
    if demote_ids:
        print(f"\nDemoted to Tier B by --demote ({len(demote_ids)}): {', '.join(demote_ids)}")
    print_diff(added, removed, added_global, removed_global)

    per_topic_counts = {tid: len(ids) for tid, ids in sorted(new_by_topic.items())}
    print(f"\nNew example_readings counts by topic: {per_topic_counts}")

    if not args.write:
        print("\nDry run — no files written. Re-run with --write to update framework.json.")
        return

    updated = apply_vector_update(framework, new_by_topic)
    with open(args.framework, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)
    print(f"\nWrote {args.framework}")


if __name__ == "__main__":
    main()
