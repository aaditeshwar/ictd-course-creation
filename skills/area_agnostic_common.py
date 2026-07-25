"""Shared helpers for area-agnostic Tier A / Tier B pipeline scripts."""
import json
import math
from pathlib import Path

from pipeline_common import DEFAULT_FRAMEWORK, DEFAULT_READINGS, DEFAULT_EXAMPLES, PROJECT_ROOT

BOOK_NOTES_PREFIX = "This is a book"
DEFAULT_SCORES_PATH = PROJECT_ROOT / "data" / "area_agnostic_relevance_scores.json"

READING_CHUNK_SIZE = 5
CASE_STUDY_CHUNK_SIZE = 5


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_framework(path=DEFAULT_FRAMEWORK):
    return load_json(path)


def load_readings(path=DEFAULT_READINGS):
    return load_json(path)["readings"]


def load_examples(path=DEFAULT_EXAMPLES):
    data = load_json(path)
    return data.get("case_studies", []), data.get("metadata", {})


def topic_ids(framework):
    return [t["id"] for t in framework["topics"]]


def is_book_reading(reading):
    """True when notes marks this as a book (Tier A even with a single topic)."""
    notes = (reading.get("notes") or "").strip()
    return notes.startswith(BOOK_NOTES_PREFIX)


def is_tier_a(reading):
    """Tier A: breadth >= 2 topics, OR any book (even a single-topic book)."""
    if is_book_reading(reading):
        return True
    topics = reading.get("topics") or []
    return len(topics) >= 2


# Multi-topic readings demoted from vector to Tier B relevance scoring.
DEFAULT_DEMOTE_TO_TIER_B_IDS = (
    "2022_community_participation",
    "aies_2025_part2_embodied_ai_at_the_margins_postcolonial",
    "climate_change_ai_climateq_a_bridging_the_gap_between",
    "compass_2021_opaque_obstacles_the_role_of_stigma",
    "cscw_2022_2_sensemystreet_sensor_commissioning_toolkit_for_communities",
    "cscw_2024_2_human_centered_nlp_fact_checking_co",
    "cscw_2025_1_envisioning_ai_support_during_semi_structured",
    "ghtc_2024_an_interactive_framework_understanding_community_desires",
    "ictd_2022_opportunities_for_women_in_computing_perspective",
    "ijcai_2023_disentangling_societal_inequality_from_model_biases",
    "itid_2017_victim_mother_or_untapped_resource_discourse",
    "itid_2018_gender_mobile_and_mobile_internet_maintenance",
    "jcss_2025_an_algorithmic_audit_of_online_matrimonial",
)


def split_tiers(readings, framework=None, demote_to_tier_b_ids=None, keep_reading_ids=None):
    """Split area-agnostic readings into Tier A (vector) and Tier B (example mapping).

    Tier A: in area_agnostic_topic_vector when framework is provided, else breadth>=2/books
            plus keep-list ids, minus demote list.
    Tier B: area-agnostic readings NOT in the vector — only these are relevance-scored.
    """
    demote = set(demote_to_tier_b_ids if demote_to_tier_b_ids is not None else DEFAULT_DEMOTE_TO_TIER_B_IDS)
    keep = set(keep_reading_ids if keep_reading_ids is not None else DEFAULT_KEEP_READING_IDS)
    area_agnostic = [r for r in readings if r.get("area_agnostic")]
    tier_a = [r for r in area_agnostic if is_tier_a(r) and r["id"] not in demote]

    if framework is not None:
        vector_ids = current_vector_reading_ids(framework)
    else:
        vector_ids = {r["id"] for r in tier_a}
        vector_ids.update(rid for rid in keep if rid not in demote)

    tier_b = [r for r in area_agnostic if r["id"] not in vector_ids]
    return area_agnostic, tier_a, tier_b


def tier_b_for_scoring(readings, framework):
    """Area-agnostic readings excluded from the topic vector (Tier B only)."""
    vector_ids = current_vector_reading_ids(framework)
    return [r for r in readings if r.get("area_agnostic") and r["id"] not in vector_ids]


def purge_tier_a_from_scores(scores_data, framework):
    """Remove any scores/chunks for readings in area_agnostic_topic_vector."""
    vector_ids = current_vector_reading_ids(framework)
    if not vector_ids:
        return scores_data, 0, 0

    old_scores = len(scores_data.get("scores") or [])
    old_chunks = len(scores_data.get("completed_chunks") or [])
    scores_data["scores"] = [
        s for s in (scores_data.get("scores") or [])
        if s.get("reading_id") not in vector_ids
    ]
    scores_data["completed_chunks"] = [
        c for c in (scores_data.get("completed_chunks") or [])
        if not any(rid in vector_ids for rid in (c.get("reading_ids") or []))
    ]
    removed_scores = old_scores - len(scores_data["scores"])
    removed_chunks = old_chunks - len(scores_data["completed_chunks"])
    return scores_data, removed_scores, removed_chunks


def chunk_list(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def chunk_pair_count(n_readings, n_case_studies, reading_size=READING_CHUNK_SIZE,
                     case_study_size=CASE_STUDY_CHUNK_SIZE):
    if not n_readings or not n_case_studies:
        return 0
    return math.ceil(n_readings / reading_size) * math.ceil(n_case_studies / case_study_size)


def readings_for_topic(tier_b_readings, topic_id):
    return [r for r in tier_b_readings if topic_id in (r.get("topics") or [])]


def case_studies_for_topic(case_studies, topic_id):
    return [cs for cs in case_studies if topic_id in (cs.get("topics_covered") or [])]


def current_vector_reading_ids(framework):
    ids = set()
    for entry in framework.get("area_agnostic_topic_vector", []):
        ids.update(entry.get("example_readings") or [])
    return ids


# Hand-curated exceptions: keep in vector even when not Tier A (single-topic, non-book).
DEFAULT_KEEP_READING_IDS = (
    "2023_how_remote_sensing_works_0a5662",
    "shekhar_spatiotemporal_data_mining",
    "dell_yours_is_better_bias",
    "kohavi_controlled_experiments_web",
    "alsop_heinsohn_empowerment",
    "heeks_ict4d_manifesto",
    "kleine_ict4what",
    "piketty_inequality_newyorker",
    "sen_capability_approach",
    "smillie_mastering_machine",
    "streeck_how_will_capitalism_end",
    "wong_villacres_assets_based_design",
)


def rebuild_vector_membership(
    tier_a_readings,
    framework=None,
    readings_by_id=None,
    keep_reading_ids=None,
    demote_to_tier_b_ids=None,
):
    """topic_id -> sorted list of reading ids."""
    demote = set(
        demote_to_tier_b_ids
        if demote_to_tier_b_ids is not None
        else DEFAULT_DEMOTE_TO_TIER_B_IDS
    )
    by_topic = {}
    for reading in tier_a_readings:
        if reading["id"] in demote:
            continue
        for topic_id in reading.get("topics") or []:
            by_topic.setdefault(topic_id, set()).add(reading["id"])

    # Retain books already listed in the current vector (even single-topic books).
    if framework and readings_by_id:
        for entry in framework.get("area_agnostic_topic_vector", []):
            topic_id = entry["id"]
            for rid in entry.get("example_readings") or []:
                reading = readings_by_id.get(rid)
                if reading and is_book_reading(reading):
                    by_topic.setdefault(topic_id, set()).add(rid)

    if readings_by_id and keep_reading_ids:
        for rid in keep_reading_ids:
            if rid in demote:
                continue
            reading = readings_by_id.get(rid)
            if not reading:
                continue
            for topic_id in reading.get("topics") or []:
                by_topic.setdefault(topic_id, set()).add(rid)

    return {topic_id: sorted(ids) for topic_id, ids in sorted(by_topic.items())}


def cache_chunk_key(topic_id, reading_ids, case_study_ids, backend, model):
    return {
        "topic": topic_id,
        "reading_ids": list(reading_ids),
        "case_study_ids": list(case_study_ids),
        "backend": backend,
        "model": model,
    }


def chunk_key_matches(stored, topic_id, reading_ids, case_study_ids, backend, model):
    return (
        stored.get("topic") == topic_id
        and stored.get("reading_ids") == list(reading_ids)
        and stored.get("case_study_ids") == list(case_study_ids)
        and stored.get("backend") == backend
        and stored.get("model") == model
    )
