"""
Runs the ictd-case-study-generation skill (see skill_examples_case_study_generation.md)
locally using the Claude API, producing examples.json from framework.json + readings.json.

v2: two-stage per area (domain discovery, then reading assignment), with chunking for large
areas, checkpointing so a crash doesn't lose completed areas, and a cross-area dedup/merge pass
for domains independently (re)discovered under more than one area -- see the design discussion
in chat for why this replaced the single-call-per-area v1 approach once the corpus grew past
~150 readings/area.

Install:
    pip install anthropic

Set your API key:
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python generate_examples_via_api.py \
        --framework framework.json --readings readings.json --out examples.json

    # resume after a crash/interruption -- skips areas that already have a checkpoint:
    python generate_examples_via_api.py --resume ...

    # force full re-run, ignoring any existing checkpoints:
    python generate_examples_via_api.py --force ...

Cost/scale note: roughly 2 calls per area-chunk (domain discovery + reading assignment), where
an area is split into ceil(n_readings / CHUNK_SIZE) chunks. At CHUNK_SIZE=80, a 1000-reading
corpus spread across 11 areas (~90 readings/area average, some areas much larger) works out to
roughly 25-40 calls total, plus one cross-area merge pass and one final reconciliation call --
still cheap enough to re-run whenever readings.json changes materially.
"""
import json
import re
import os
import argparse
from collections import defaultdict

import anthropic

MODEL = "claude-opus-4-8"
CHUNK_SIZE = 80  # readings per API call for stage 1/2 -- lower this if you see truncated JSON
CHECKPOINT_DIR = "checkpoints"


# ---------------- shared helpers (also used by dedup.py-style matching) ----------------

STOPWORDS = {
    'the', 'and', 'of', 'in', 'using', 'evidence', 'from', 'for', 'with', 'on', 'to', 'a', 'an',
    'study', 'case', 'india', 'indian', 'analysis', 'paper', 'data', 'new', 'review', 'based',
}


def sig_words(text):
    s = re.sub(r'[^a-z0-9 ]', ' ', text.lower())
    return {w for w in s.split() if len(w) >= 4 and w not in STOPWORDS}


def word_overlap_score(a, b):
    sa, sb = sig_words(a), sig_words(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def chunk_list(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def extract_json(text, kind="array"):
    pattern = r"\[.*\]" if kind == "array" else r"\{.*\}"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def call_claude(client, prompt, max_tokens=4000, tools=None):
    kwargs = {"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if tools:
        kwargs["tools"] = tools
    response = client.messages.create(**kwargs)
    text = "".join(block.text for block in response.content if block.type == "text")
    truncated = response.stop_reason == "max_tokens"
    return text, truncated


# ---------------- input loading ----------------

def load_inputs(framework_path, readings_path):
    with open(framework_path, encoding="utf-8") as f:
        framework = json.load(f)
    with open(readings_path, encoding="utf-8") as f:
        readings = json.load(f)["readings"]
    readings_by_id = {r["id"]: r for r in readings}
    return framework, readings, readings_by_id


def readings_for_area(readings, area_id):
    """Membership-based, not primary-only -- a reading tagged areas=[forests_restoration, labour]
    shows up under BOTH areas' lists. This is what lets a genuinely cross-area domain like MGNREGA
    get discovered independently from either area; the cross-area merge pass (stage 3) then
    reconciles the resulting duplicate proposals into one case study."""
    return [r for r in readings if not r.get("area_agnostic") and area_id in r["areas"]]


def compact_dump(readings):
    return "\n".join(
        f"{r['id']} | {r['title'][:100]} | topics={r['topics']} | axes={r['cross_cutting_axes']}"
        for r in readings
    )


def topic_order_ids(framework):
    return [t["id"] for t in sorted(framework["topics"], key=lambda t: t["sequence"])]


# ---------------- stage 1: domain discovery (names ONLY -- see stage 2.5 for why description
# moved out of here: asking for a description before any reading is assigned makes the model
# write a speculative, low-effort summary from skimmed titles, and it was empirically producing
# empty/throwaway descriptions across real runs) ----------------

STAGE1_PROMPT = """You are identifying recurring real-world DOMAINS within the "{area_name}" area \
of an ICTD course reading list, following the ictd-case-study-generation skill.

A domain is a recurring pattern of similar interventions/research (e.g. "voice-based agricultural \
extension", "REDD+ forest carbon offset integrity") -- NOT a single project, NOT "papers that share \
a topic tag". Prefer domains likely to span multiple topics (problem_discovery, cs_fundamentals, \
ethnographic_design, sociotechnical_dynamics, impact_evaluation, operations_scale) over single-topic \
clusters. Don't force every reading into a domain -- some will be one-offs; just don't propose a \
domain for them.

READINGS IN THIS AREA (or chunk of it):
{dump}

Respond with ONLY a JSON array of candidate domain NAMES (just names -- reading assignment and
descriptions happen in later steps, don't do them here):
["Human-readable domain name", "Another domain name", "..."]
"""


def stage1_discover_domains(client, area, area_readings):
    chunks = chunk_list(area_readings, CHUNK_SIZE)
    all_names = []
    for i, chunk in enumerate(chunks):
        print(f"  stage1 [{area['id']}] chunk {i+1}/{len(chunks)} ({len(chunk)} readings)...")
        prompt = STAGE1_PROMPT.format(area_name=area["name"], dump=compact_dump(chunk))
        text, truncated = call_claude(client, prompt, max_tokens=1500)
        if truncated:
            print(f"    WARNING: response truncated -- consider lowering CHUNK_SIZE")
        names = extract_json(text, "array") or []
        all_names.extend(n for n in names if isinstance(n, str) and n.strip())

    if len(chunks) > 1:
        all_names = merge_similar_domain_names(all_names)
    return all_names


def merge_similar_domain_names(names, threshold=0.6):
    """Fuzzy-merge near-duplicate names (same word-overlap approach as dedup.py), which happens
    when multiple chunks of a large area independently notice the same domain."""
    merged = []
    for name in names:
        if not any(word_overlap_score(name, m) >= threshold for m in merged):
            merged.append(name)
    return merged


# ---------------- stage 2: reading assignment + background concepts, per already-named domain ----------------

STAGE2_PROMPT = """You previously identified these candidate domain names within the "{area_name}" area:
{domains_list}

Now assign specific readings to each domain from this list (or chunk of it):
{dump}

For EACH domain, also identify domain-specific background concepts its assigned readings assume \
but don't teach (a metric, physical process, named theory, or institutional mechanism mentioned \
without explanation). For each concept, use web search to find 1-2 REAL, freely-accessible, \
introductory learning resources (primer, lecture notes, course module, agency guide -- not another \
research paper). Only include a resource if you found a real URL via search -- never fabricate one. \
Leave background_concepts empty for a domain if there's no real jargon gap.

Not every reading in the list needs to be assigned -- leave out genuine one-offs. If a domain name
turns out to have no readings that actually fit once you look closely, just don't include it in
your response at all (better than force-assigning weak matches).

Respond with ONLY a JSON array:
[
  {{
    "domain_name": "must exactly match one of the domain names given above",
    "reading_ids": ["id_from_the_list_above", "..."],
    "background_concepts": [
      {{"concept": "...", "why_needed": "...",
        "suggested_resources": [{{"title": "...", "url": "...", "type": "primer|lecture_notes|course_module|agency_guide"}}]}}
    ]
  }}
]
"""


def stage2_assign_readings(client, area, domain_names, area_readings):
    if not domain_names:
        return {}
    domains_list = "\n".join(f"- {n}" for n in domain_names)
    chunks = chunk_list(area_readings, CHUNK_SIZE)

    # accumulate per domain_name across chunks
    assignments = defaultdict(lambda: {"reading_ids": set(), "background_concepts": []})
    for i, chunk in enumerate(chunks):
        print(f"  stage2 [{area['id']}] chunk {i+1}/{len(chunks)} ({len(chunk)} readings)...")
        prompt = STAGE2_PROMPT.format(area_name=area["name"], domains_list=domains_list,
                                       dump=compact_dump(chunk))
        text, truncated = call_claude(
            client, prompt, max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
        )
        if truncated:
            print(f"    WARNING: response truncated -- consider lowering CHUNK_SIZE")
        results = extract_json(text, "array") or []
        valid_ids = {r["id"] for r in chunk}
        for res in results:
            dn = res.get("domain_name")
            if dn is None:
                continue
            got_ids = [rid for rid in res.get("reading_ids", []) if rid in valid_ids]
            assignments[dn]["reading_ids"].update(got_ids)
            if res.get("background_concepts") and not assignments[dn]["background_concepts"]:
                assignments[dn]["background_concepts"] = res["background_concepts"]

    return assignments


# ---------------- stage 2.5 (NEW): write descriptions grounded in actual assigned readings ----------------
# This replaced asking for a description in stage 1. Root cause of the empty-description problem:
# stage 1 asked the model to describe a domain before any reading was actually assigned to it,
# which is a speculative, low-stakes task from the model's perspective (skim some titles, guess a
# summary) -- across real runs this was reliably producing empty or throwaway values, especially
# for domains later in a long array. Writing the description AFTER assignment, grounded in the
# domain's real member reading titles, is a well-defined summarization task the model does
# reliably, and produces a more accurate description besides (it's describing what's actually in
# the domain, not what the model guessed would be).

MIN_DESCRIPTION_LEN = 30  # chars -- anything shorter is treated as a failed/empty description

DESCRIBE_PROMPT = """For each domain below, write a 2-3 sentence description of what it covers, \
grounded in the actual titles of the readings assigned to it. Every description must be a real, \
substantive summary -- never leave one empty or a placeholder.

{domains_with_readings}

Respond with ONLY a JSON object mapping domain name -> description:
{{"Domain name exactly as given": "2-3 sentence description", "...": "..."}}
"""

DESCRIBE_SINGLE_PROMPT = """Write a 2-3 sentence description of this domain, grounded in the \
actual titles of its assigned readings. It must be a real, substantive summary -- not empty or \
a placeholder.

Domain: {name}
Readings:
{reading_titles}

Respond with ONLY the description text, no JSON, no quotes, no preamble.
"""


def write_domain_descriptions(client, area, draft_case_studies, readings_by_id):
    """draft_case_studies: list of dicts with at least 'name' and 'readings' (id list) already
    set. Returns {name: description}, with a validated non-empty description for every domain
    (individually retried once if the batch call comes back empty/short for it, then falls back
    to an auto-generated stub -- clearly flagged -- rather than ever silently leaving it blank)."""
    if not draft_case_studies:
        return {}

    def titles_block(cs):
        titles = [readings_by_id[rid]["title"] for rid in cs["readings"] if rid in readings_by_id]
        return "\n".join(f"  - {t}" for t in titles[:25])  # cap per-domain title list for token sanity

    domains_with_readings = "\n\n".join(
        f"Domain: {cs['name']}\nReadings:\n{titles_block(cs)}" for cs in draft_case_studies
    )
    prompt = DESCRIBE_PROMPT.format(domains_with_readings=domains_with_readings)
    text, truncated = call_claude(client, prompt, max_tokens=3000)
    if truncated:
        print(f"    WARNING: description-writing response truncated for area {area['id']}")
    descriptions = extract_json(text, "object") or {}

    # validate + repair per domain
    final = {}
    for cs in draft_case_studies:
        desc = descriptions.get(cs["name"], "")
        if desc and len(desc.strip()) >= MIN_DESCRIPTION_LEN:
            final[cs["name"]] = desc.strip()
            continue

        print(f"    Description missing/short for '{cs['name']}', retrying individually...")
        retry_prompt = DESCRIBE_SINGLE_PROMPT.format(name=cs["name"], reading_titles=titles_block(cs))
        retry_text, _ = call_claude(client, retry_prompt, max_tokens=500)
        retry_text = retry_text.strip()
        if retry_text and len(retry_text) >= MIN_DESCRIPTION_LEN:
            final[cs["name"]] = retry_text
        else:
            titles = [readings_by_id[rid]["title"] for rid in cs["readings"] if rid in readings_by_id]
            stub = ("[AUTO-GENERATED - NEEDS REVIEW] Domain grouping readings including: "
                    + "; ".join(titles[:3]) + ("..." if len(titles) > 3 else "."))
            print(f"    Individual retry also failed for '{cs['name']}' -- using auto-generated stub")
            final[cs["name"]] = stub

    return final




def checkpoint_path(out_dir, area_id):
    return os.path.join(out_dir, CHECKPOINT_DIR, f"{area_id}.json")


def load_checkpoint(out_dir, area_id):
    p = checkpoint_path(out_dir, area_id)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_checkpoint(out_dir, area_id, case_studies):
    p = checkpoint_path(out_dir, area_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(case_studies, f, indent=2)


# ---------------- finalize (auto-derive coverage, same as v1) ----------------

def finalize_case_study(id_, name, areas, description, reading_ids, background_concepts,
                         readings_by_id, topic_order, axis_order, valid_areas):
    topics, axes = set(), set()
    for rid in reading_ids:
        r = readings_by_id.get(rid)
        if r is None:
            continue
        topics.update(r["topics"])
        axes.update(r["cross_cutting_axes"])
    return {
        "id": id_, "name": name,
        "areas": [a for a in areas if a in valid_areas],
        "description": description,
        "topics_covered": [t for t in topic_order if t in topics],
        "cross_cutting_axes": [a for a in axis_order if a in axes],
        "readings": [rid for rid in reading_ids if rid in readings_by_id],
        "background_concepts": background_concepts or [],
    }


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---------------- stage 3 (NEW): cross-area dedup/merge ----------------

def cross_area_merge(case_studies, overlap_threshold=0.5):
    """Two case studies proposed under different areas (e.g. one discovered while scanning
    'labour', one discovered while scanning 'forests_restoration') can be the same real-world
    domain, since stage 1 runs independently per area with no visibility into other areas'
    proposals. Merge any pair whose reading sets overlap above threshold (Jaccard on reading ids),
    keeping the one with more readings as the base and folding the other's area in as secondary."""
    merged = []
    consumed = set()
    for i, cs in enumerate(case_studies):
        if i in consumed:
            continue
        group = [cs]
        set_i = set(cs["readings"])
        for j in range(i + 1, len(case_studies)):
            if j in consumed:
                continue
            other = case_studies[j]
            set_j = set(other["readings"])
            if not set_i or not set_j:
                continue
            jaccard = len(set_i & set_j) / len(set_i | set_j)
            if jaccard >= overlap_threshold:
                group.append(other)
                consumed.add(j)
        if len(group) == 1:
            merged.append(cs)
        else:
            # keep the largest as base, fold in areas + union readings + concat background_concepts
            group.sort(key=lambda c: len(c["readings"]), reverse=True)
            base = dict(group[0])
            all_readings = set(base["readings"])
            all_areas = list(base["areas"])
            all_bg = list(base["background_concepts"])
            for other in group[1:]:
                all_readings.update(other["readings"])
                for a in other["areas"]:
                    if a not in all_areas:
                        all_areas.append(a)
                for bg in other["background_concepts"]:
                    if bg not in all_bg:
                        all_bg.append(bg)
            base["readings"] = sorted(all_readings)
            base["areas"] = all_areas
            base["background_concepts"] = all_bg
            names = ", ".join(c["name"] for c in group)
            print(f"  Merged {len(group)} cross-area duplicates into '{base['name']}' (was: {names})")
            merged.append(base)
    return merged


def recompute_coverage(case_studies, readings_by_id, topic_order, axis_order):
    for cs in case_studies:
        topics, axes = set(), set()
        for rid in cs["readings"]:
            r = readings_by_id.get(rid)
            if r is None:
                continue
            topics.update(r["topics"])
            axes.update(r["cross_cutting_axes"])
        cs["topics_covered"] = [t for t in topic_order if t in topics]
        cs["cross_cutting_axes"] = [a for a in axis_order if a in axes]
    return case_studies


# ---------------- stage 4: coverage diff + reconciliation (same idea as v1, now chunked) ----------------

def reconcile_uncovered(client, readings, case_studies, readings_by_id, topic_order, axis_order, valid_areas):
    covered = {rid for cs in case_studies for rid in cs["readings"]}
    uncovered = [r for r in readings if not r.get("area_agnostic") and r["areas"] and r["id"] not in covered]
    if not uncovered:
        print("Coverage diff: nothing uncovered.")
        return case_studies

    print(f"Coverage diff: {len(uncovered)} readings uncovered, reconciling in chunks of {CHUNK_SIZE}...")
    existing_dump = "\n".join(f"{cs['id']}: {cs['name']} (areas={cs['areas']})" for cs in case_studies)

    for chunk in chunk_list(uncovered, CHUNK_SIZE):
        uncovered_dump = "\n".join(
            f"{r['id']} | {r['title'][:100]} | areas={r['areas']} | topics={r['topics']}" for r in chunk
        )
        prompt = f"""These readings were not assigned to any case study:
{uncovered_dump}

Existing case studies:
{existing_dump}

For each, either (a) fold it into the single best-fitting existing case study by id, or (b) if \
several share a subject not covered by any existing case study, propose ONE new small case study.

Respond with ONLY: {{"fold_into_existing": {{"case_study_id": ["reading_id", ...]}}, \
"new_case_studies": [{{"id": "...", "name": "...", "areas": ["..."], "description": "...", "reading_ids": ["..."]}}]}}"""
        text, truncated = call_claude(client, prompt, max_tokens=4000)
        result = extract_json(text, "object") or {}

        by_id = {cs["id"]: cs for cs in case_studies}
        for cs_id, rids in result.get("fold_into_existing", {}).items():
            if cs_id in by_id:
                by_id[cs_id]["readings"] = list(set(by_id[cs_id]["readings"]) | set(rids))
        for raw in result.get("new_case_studies", []):
            desc = raw.get("description", "")
            if not desc or len(desc.strip()) < MIN_DESCRIPTION_LEN:
                titles = [readings_by_id[rid]["title"] for rid in raw.get("reading_ids", [])
                          if rid in readings_by_id]
                desc = ("[AUTO-GENERATED - NEEDS REVIEW] Domain grouping readings including: "
                        + "; ".join(titles[:3]) + ("..." if len(titles) > 3 else "."))
                print(f"    Reconciliation new case study '{raw.get('name')}' had no usable "
                      f"description -- using auto-generated stub")
            case_studies.append(finalize_case_study(
                raw.get("id", slugify(raw["name"])), raw["name"], raw.get("areas", []),
                desc, raw.get("reading_ids", []), [],
                readings_by_id, topic_order, axis_order, valid_areas,
            ))

    return recompute_coverage(case_studies, readings_by_id, topic_order, axis_order)


# ---------------- orchestration ----------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", default="framework.json")
    parser.add_argument("--readings", default="readings.json")
    parser.add_argument("--out", default="examples.json")
    parser.add_argument("--out-dir", default=".", help="where checkpoints/ is stored")
    parser.add_argument("--force", action="store_true", help="ignore existing checkpoints")
    args = parser.parse_args()

    client = anthropic.Anthropic()
    framework, readings, readings_by_id = load_inputs(args.framework, args.readings)
    topic_order = topic_order_ids(framework)
    axis_order = [a["id"] for a in framework["cross_cutting_axes"]]
    valid_areas = {a["id"] for a in framework["areas"]}

    all_case_studies = []
    for area in framework["areas"]:
        if not args.force:
            cached = load_checkpoint(args.out_dir, area["id"])
            if cached is not None:
                print(f"Area {area['id']}: using checkpoint ({len(cached)} case studies)")
                all_case_studies.extend(cached)
                continue

        area_readings = readings_for_area(readings, area["id"])
        print(f"Area {area['id']}: {len(area_readings)} readings")
        if not area_readings:
            save_checkpoint(args.out_dir, area["id"], [])
            continue

        domain_names = stage1_discover_domains(client, area, area_readings)
        print(f"  -> {len(domain_names)} candidate domains")
        assignments = stage2_assign_readings(client, area, domain_names, area_readings)

        # build drafts (name + assigned readings) first, dropping anything with zero readings,
        # THEN write descriptions grounded in the real assigned reading titles (stage 2.5) --
        # description must come after assignment, see write_domain_descriptions' docstring
        drafts = []
        for name in domain_names:
            a = assignments.get(name, {"reading_ids": set(), "background_concepts": []})
            if not a["reading_ids"]:
                continue  # domain proposed but nothing actually got assigned -- drop it
            drafts.append({"name": name, "readings": sorted(a["reading_ids"]),
                            "background_concepts": a["background_concepts"]})

        descriptions = write_domain_descriptions(client, area, drafts, readings_by_id)

        area_case_studies = [
            finalize_case_study(
                f"{area['id']}_{slugify(d['name'])}", d["name"], [area["id"]],
                descriptions.get(d["name"], ""), d["readings"], d["background_concepts"],
                readings_by_id, topic_order, axis_order, valid_areas,
            )
            for d in drafts
        ]

        save_checkpoint(args.out_dir, area["id"], area_case_studies)
        all_case_studies.extend(area_case_studies)

    print(f"\n{len(all_case_studies)} case studies before cross-area merge")
    all_case_studies = cross_area_merge(all_case_studies)
    all_case_studies = recompute_coverage(all_case_studies, readings_by_id, topic_order, axis_order)
    print(f"{len(all_case_studies)} case studies after cross-area merge")

    all_case_studies = reconcile_uncovered(
        client, readings, all_case_studies, readings_by_id, topic_order, axis_order, valid_areas
    )

    covered = {rid for cs in all_case_studies for rid in cs["readings"]}
    metadata = {
        "purpose": "Domain-level case studies within each framework area, generated via the "
                   "ictd-case-study-generation skill (v2: two-stage per-area + cross-area merge) "
                   "using the Claude API.",
        "schema_note": "topics_covered/cross_cutting_axes are auto-derived, not independently "
                       "curated by the model. background_concepts URLs were grounded via web "
                       "search but should still be spot-checked before publishing.",
        "total_case_studies": len(all_case_studies),
        "readings_referenced": len(covered),
        "readings_total_in_corpus": len(readings),
        "coverage_note": "Gap is expected to be almost entirely area_agnostic=true readings.",
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"metadata": metadata, "case_studies": all_case_studies}, f, indent=2)

    print(f"\nDone. {len(all_case_studies)} case studies, {len(covered)}/{len(readings)} "
          f"readings referenced. Written to {args.out}")
    print("Recommended: run the skill's step-5 validation checks (unique ids, no empty case "
          "studies, valid vocabulary) and spot-check background_concepts URLs and the cross-area "
          "merge decisions before treating this as final.")


if __name__ == "__main__":
    main()
