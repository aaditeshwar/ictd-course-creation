"""
Runs the ictd-case-study-generation skill (see skill_examples_case_study_generation.md)
locally using the Claude API, producing examples.json from framework.json + readings.json.

v2: two-stage per area (domain discovery, then reading assignment), with chunking for large
areas, checkpointing so a crash doesn't lose completed areas, and a cross-area dedup/merge pass
for domains independently (re)discovered under more than one area.

Install:
    pip install anthropic

Set your API key in .env (see .env.example):
    ANTHROPIC_API_KEY=sk-ant-...

Run:
    python skills/generate_examples_via_api.py --dry-run   # corpus stats + sizing recommendations
    python skills/generate_examples_via_api.py             # full run

    # ignore cached stage-1/stage-2/checkpoint files:
    python skills/generate_examples_via_api.py --force

Intermediate API outputs are cached under --output-dir (default data/examples-output):
    stage1/{area_id}_chunk{N}.json      domain names
    stage2/{area_id}_chunk{N}.json      reading assignments
    stage25/{area_id}.json              domain descriptions (grounded in assignments)
    checkpoints/{area_id}.json
"""
import json
import re
import os
import math
import argparse
import sys
from collections import defaultdict
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
from pipeline_common import load_dotenv, get_anthropic_model

# Tuned for ~1025 readings / 11 areas (see --dry-run output for derivation).
STAGE1_MAX_TOKENS = 2048          # domain names only (no descriptions)
STAGE2_MAX_TOKENS = 8192
STAGE25_MAX_TOKENS = 8192         # batch domain descriptions per area
STAGE25_SINGLE_MAX_TOKENS = 500   # individual retry
DESCRIBE_BATCH_SIZE = 10          # split stage 2.5 when an area has many domains
RECONCILE_MAX_TOKENS = 8192
MIN_DESCRIPTION_LEN = 30

DEFAULT_FRAMEWORK = "data/framework.json"
DEFAULT_READINGS = "data/readings.json"
DEFAULT_OUTPUT_DIR = "data/examples-output"
DEFAULT_OUT = "data/examples.json"

STAGE1_DIR = "stage1"
STAGE2_DIR = "stage2"
STAGE25_DIR = "stage25"
CHECKPOINT_DIR = "checkpoints"

# Approximate chars-per-token for English prose / JSON (conservative for sizing).
CHARS_PER_TOKEN = 4


# ---------------- shared helpers ----------------

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


def est_tokens(text):
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def call_claude(client, prompt, max_tokens=4000, tools=None):
    kwargs = {
        "model": get_anthropic_model(),
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
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
    return [r for r in readings if not r.get("area_agnostic") and area_id in r["areas"]]


def compact_dump(readings):
    return "\n".join(
        f"{r['id']} | {r['title'][:100]} | topics={r['topics']} | axes={r['cross_cutting_axes']}"
        for r in readings
    )


def topic_order_ids(framework):
    return [t["id"] for t in sorted(framework["topics"], key=lambda t: t["sequence"])]


def stage_cache_path(output_dir, stage, area_id, chunk_idx):
    return os.path.join(output_dir, stage, f"{area_id}_chunk{chunk_idx}.json")


def load_stage_cache(output_dir, stage, area_id, chunk_idx):
    path = stage_cache_path(output_dir, stage, area_id, chunk_idx)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_stage_cache(output_dir, stage, area_id, chunk_idx, data):
    path = stage_cache_path(output_dir, stage, area_id, chunk_idx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def checkpoint_path(output_dir, area_id):
    return os.path.join(output_dir, CHECKPOINT_DIR, f"{area_id}.json")


def load_checkpoint(output_dir, area_id):
    p = checkpoint_path(output_dir, area_id)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_checkpoint(output_dir, area_id, case_studies):
    p = checkpoint_path(output_dir, area_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(case_studies, f, indent=2)


def stage25_cache_path(output_dir, area_id):
    return os.path.join(output_dir, STAGE25_DIR, f"{area_id}.json")


def load_stage25_cache(output_dir, area_id):
    path = stage25_cache_path(output_dir, area_id)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_stage25_cache(output_dir, area_id, descriptions):
    path = stage25_cache_path(output_dir, area_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(descriptions, f, indent=2)


def normalize_stage1_names(cached_chunk):
    """Accept new string-only caches or legacy {name, description} objects."""
    names = []
    for item in cached_chunk or []:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("domain_name")
            if name and str(name).strip():
                names.append(str(name).strip())
    return names


def merge_similar_domain_names(names, threshold=0.6):
    merged = []
    for name in names:
        if not any(word_overlap_score(name, m) >= threshold for m in merged):
            merged.append(name)
    return merged


def checkpoint_is_complete(output_dir, area_id, cached):
    if not cached:
        return False
    if not os.path.exists(stage25_cache_path(output_dir, area_id)):
        return False
    return all(len(cs.get("description", "").strip()) >= MIN_DESCRIPTION_LEN for cs in cached)


def build_drafts(domain_names, assignments):
    drafts = []
    for name in domain_names:
        a = assignments.get(name, {"reading_ids": set(), "background_concepts": []})
        if not a["reading_ids"]:
            continue
        drafts.append({
            "name": name,
            "readings": sorted(a["reading_ids"]),
            "background_concepts": a["background_concepts"],
        })
    return drafts


def titles_block(reading_ids, readings_by_id, max_titles=25):
    titles = [readings_by_id[rid]["title"] for rid in reading_ids if rid in readings_by_id]
    return "\n".join(f"  - {t}" for t in titles[:max_titles])


def estimate_describe_prompt_chars(drafts, readings_by_id):
    blocks = []
    for draft in drafts:
        blocks.append(f"Domain: {draft['name']}\nReadings:\n{titles_block(draft['readings'], readings_by_id)}")
    return len(DESCRIBE_PROMPT.format(domains_with_readings="\n\n".join(blocks)))


def load_drafts_from_stage_caches(area, area_readings, readings_by_id, output_dir, chunk_size):
    """Reconstruct drafts from cached stage1+2 without API calls."""
    chunks = chunk_list(area_readings, chunk_size)
    all_names = []
    for i in range(len(chunks)):
        cached = load_stage_cache(output_dir, STAGE1_DIR, area["id"], i)
        if cached is None:
            return None
        all_names.extend(normalize_stage1_names(cached))
    if len(chunks) > 1:
        all_names = merge_similar_domain_names(all_names)

    assignments = defaultdict(lambda: {"reading_ids": set(), "background_concepts": []})
    for i, chunk in enumerate(chunks):
        cached = load_stage_cache(output_dir, STAGE2_DIR, area["id"], i)
        if cached is None:
            return None
        valid_ids = {r["id"] for r in chunk}
        for res in cached:
            dn = res.get("domain_name")
            if dn is None:
                continue
            got_ids = [rid for rid in res.get("reading_ids", []) if rid in valid_ids]
            assignments[dn]["reading_ids"].update(got_ids)
            if res.get("background_concepts") and not assignments[dn]["background_concepts"]:
                assignments[dn]["background_concepts"] = res["background_concepts"]
    return build_drafts(all_names, assignments)


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


# ---------------- dry-run / sizing analysis ----------------

def print_corpus_stats(framework, readings, chunk_size, output_dir=None, readings_by_id=None):
    areas = framework["areas"]
    topics = topic_order_ids(framework)
    topic_short = [t[:8] for t in topics]

    print("\n=== READINGS PER AREA ===")
    print(f"{'area_id':<28} {'count':>6}  name")
    print("-" * 72)
    area_counts = {}
    for area in areas:
        n = len(readings_for_area(readings, area["id"]))
        area_counts[area["id"]] = n
        print(f"{area['id']:<28} {n:>6}  {area['name']}")

    non_agnostic = sum(1 for r in readings if not r.get("area_agnostic") and r.get("areas"))
    agnostic = sum(1 for r in readings if r.get("area_agnostic"))
    print(f"\nTotal readings: {len(readings)}  (area-tagged: {non_agnostic}, area_agnostic: {agnostic})")

    print("\n=== AREA x TOPIC (readings tagged with both area and topic) ===")
    header = f"{'area_id':<28}" + "".join(f"{s:>9}" for s in topic_short) + f"{'TOTAL':>7}"
    print(header)
    print("-" * len(header))
    for area in areas:
        ar = readings_for_area(readings, area["id"])
        counts = [sum(1 for r in ar if t in r["topics"]) for t in topics]
        print(f"{area['id']:<28}" + "".join(f"{c:9d}" for c in counts) + f"{len(ar):7d}")

    print(f"\n=== COMPACT DUMP SIZES (chunk_size={chunk_size}) ===")
    print(f"{'area_id':<28} {'readings':>8} {'chunks':>7} {'max_chars':>10} {'avg_chars':>10} "
          f"{'est_in_tok':>11}")
    print("-" * 82)
    worst = {"area": None, "max_chars": 0, "chunks": 0}
    total_api_calls = 0
    for area in sorted(areas, key=lambda a: -area_counts[a["id"]]):
        ar = readings_for_area(readings, area["id"])
        if not ar:
            continue
        chunks = chunk_list(ar, chunk_size)
        sizes = [len(compact_dump(c)) for c in chunks]
        max_chars = max(sizes)
        avg_chars = sum(sizes) // len(sizes)
        total_api_calls += len(chunks) * 2
        print(f"{area['id']:<28} {len(ar):>8} {len(chunks):>7} {max_chars:>10} {avg_chars:>10} "
              f"{est_tokens(compact_dump(chunks[sizes.index(max_chars)])):>11}")
        if max_chars > worst["max_chars"]:
            worst = {"area": area["id"], "max_chars": max_chars, "chunks": len(chunks)}

    stage1_prompt_overhead = est_tokens(STAGE1_PROMPT.format(area_name="X", dump=""))
    stage25_calls = 0
    stage25_worst = {"area": None, "domains": 0, "est_in_tok": 0, "batches": 0}

    print(f"\n=== STAGE 2.5 DESCRIPTION SIZES (from cached stage1/2 if present) ===")
    print(f"{'area_id':<28} {'drafts':>7} {'batches':>8} {'est_in_tok':>11}")
    print("-" * 60)
    for area in sorted(areas, key=lambda a: -area_counts[a["id"]]):
        ar = readings_for_area(readings, area["id"])
        if not ar:
            continue
        drafts = None
        if output_dir and os.path.isdir(output_dir):
            drafts = load_drafts_from_stage_caches(area, ar, readings_by_id, output_dir, chunk_size)
        n_domains = len(drafts) if drafts else max(5, len(ar) // 12)
        batches = max(1, math.ceil(n_domains / DESCRIBE_BATCH_SIZE))
        est_in = 0
        if drafts:
            for batch in chunk_list(drafts, DESCRIBE_BATCH_SIZE):
                est_in = max(est_in, est_tokens("x" * estimate_describe_prompt_chars(batch, readings_by_id)))
        else:
            est_in = est_tokens(DESCRIBE_PROMPT.format(domains_with_readings="Domain: example\nReadings:\n  - title")) * batches
        stage25_calls += batches
        print(f"{area['id']:<28} {n_domains:>7} {batches:>8} {est_in:>11}")
        if est_in > stage25_worst["est_in_tok"]:
            stage25_worst = {"area": area["id"], "domains": n_domains, "est_in_tok": est_in, "batches": batches}

    recon_chunks = math.ceil(max(1, int(non_agnostic * 0.18)) / chunk_size)
    total_stage12 = total_api_calls
    total_stage25 = stage25_calls
    total_recon = recon_chunks

    print(f"\n=== RECOMMENDED SETTINGS (derived from corpus) ===")
    print(f"  --chunk-size {chunk_size}")
    print(f"  Stage 1+2 calls: ~{total_stage12}  |  Stage 2.5 batches: ~{total_stage25}  |  Reconcile: ~{total_recon}")
    if worst["area"]:
        print(f"  Largest stage1/2 chunk: {worst['area']} ~{worst['max_chars']} chars "
              f"(~{est_tokens('x' * worst['max_chars'])} dump + ~{stage1_prompt_overhead} prompt)")
    if stage25_worst["area"]:
        print(f"  Largest stage 2.5 batch: {stage25_worst['area']} ~{stage25_worst['est_in_tok']} input tokens "
              f"({stage25_worst['domains']} domains, {stage25_worst['batches']} batch(es))")
    print(f"  STAGE1_MAX_TOKENS={STAGE1_MAX_TOKENS}  (domain names only)")
    print(f"  STAGE2_MAX_TOKENS={STAGE2_MAX_TOKENS}  (assignments + background_concepts + web search)")
    print(f"  STAGE25_MAX_TOKENS={STAGE25_MAX_TOKENS}  (descriptions; batches of {DESCRIBE_BATCH_SIZE} domains)")
    print(f"  RECONCILE_MAX_TOKENS={RECONCILE_MAX_TOKENS}")
    if worst["max_chars"] > chunk_size * 200:
        suggested = max(40, chunk_size - 10)
        print(f"  NOTE: if stage1/2 JSON truncates, try --chunk-size {suggested}")
    if stage25_worst["est_in_tok"] > STAGE25_MAX_TOKENS * 0.7:
        print(f"  NOTE: stage 2.5 batches already capped at {DESCRIBE_BATCH_SIZE} domains; "
              f"raise STAGE25_MAX_TOKENS if descriptions truncate")
    print()


def run_dry_run(framework_path, readings_path, chunk_size, output_dir):
    framework, readings, readings_by_id = load_inputs(framework_path, readings_path)
    print(f"Dry run: {readings_path} + {framework_path}")
    if output_dir and os.path.isdir(output_dir):
        print(f"Using cached stage1/2 under: {output_dir}")
    print_corpus_stats(framework, readings, chunk_size, output_dir, readings_by_id)


# ---------------- stage 1 ----------------

def stage1_discover_domains(client, area, area_readings, output_dir, chunk_size, force):
    chunks = chunk_list(area_readings, chunk_size)
    all_names = []
    for i, chunk in enumerate(chunks):
        cached = None if force else load_stage_cache(output_dir, STAGE1_DIR, area["id"], i)
        if cached is not None:
            names = normalize_stage1_names(cached)
            print(f"  stage1 [{area['id']}] chunk {i+1}/{len(chunks)}: using cache ({len(names)} names)")
        else:
            print(f"  stage1 [{area['id']}] chunk {i+1}/{len(chunks)} ({len(chunk)} readings)...")
            prompt = STAGE1_PROMPT.format(area_name=area["name"], dump=compact_dump(chunk))
            text, truncated = call_claude(client, prompt, max_tokens=STAGE1_MAX_TOKENS)
            if truncated:
                print(f"    WARNING: response truncated -- lower --chunk-size or raise STAGE1_MAX_TOKENS")
            raw = extract_json(text, "array") or []
            names = [n for n in raw if isinstance(n, str) and n.strip()]
            if not names:
                names = normalize_stage1_names(raw)
            save_stage_cache(output_dir, STAGE1_DIR, area["id"], i, names)
        all_names.extend(names)

    if len(chunks) > 1:
        all_names = merge_similar_domain_names(all_names)
    return all_names


def stage2_assign_readings(client, area, domain_names, area_readings, output_dir, chunk_size, force):
    if not domain_names:
        return {}
    domains_list = "\n".join(f"- {n}" for n in domain_names)
    chunks = chunk_list(area_readings, chunk_size)

    assignments = defaultdict(lambda: {"reading_ids": set(), "background_concepts": []})
    for i, chunk in enumerate(chunks):
        cached = None if force else load_stage_cache(output_dir, STAGE2_DIR, area["id"], i)
        if cached is not None:
            print(f"  stage2 [{area['id']}] chunk {i+1}/{len(chunks)}: using cache")
            results = cached
        else:
            print(f"  stage2 [{area['id']}] chunk {i+1}/{len(chunks)} ({len(chunk)} readings)...")
            prompt = STAGE2_PROMPT.format(
                area_name=area["name"], domains_list=domains_list, dump=compact_dump(chunk),
            )
            text, truncated = call_claude(
                client, prompt, max_tokens=STAGE2_MAX_TOKENS,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
            )
            if truncated:
                print(f"    WARNING: response truncated -- lower --chunk-size or raise STAGE2_MAX_TOKENS")
            results = extract_json(text, "array") or []
            save_stage_cache(output_dir, STAGE2_DIR, area["id"], i, results)

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


def write_domain_descriptions(client, area, drafts, readings_by_id, output_dir, force):
    """Stage 2.5: descriptions grounded in assigned reading titles. Cached per area."""
    if not drafts:
        return {}

    if not force:
        cached = load_stage25_cache(output_dir, area["id"])
        if cached is not None:
            print(f"  stage2.5 [{area['id']}]: using cache ({len(cached)} descriptions)")
            return cached

    print(f"  stage2.5 [{area['id']}]: writing descriptions for {len(drafts)} domains...")
    final = {}
    for batch in chunk_list(drafts, DESCRIBE_BATCH_SIZE):
        domains_with_readings = "\n\n".join(
            f"Domain: {d['name']}\nReadings:\n{titles_block(d['readings'], readings_by_id)}"
            for d in batch
        )
        prompt = DESCRIBE_PROMPT.format(domains_with_readings=domains_with_readings)
        text, truncated = call_claude(client, prompt, max_tokens=STAGE25_MAX_TOKENS)
        if truncated:
            print(f"    WARNING: stage 2.5 batch truncated for {area['id']} -- "
                  f"lower DESCRIBE_BATCH_SIZE or raise STAGE25_MAX_TOKENS")
        descriptions = extract_json(text, "object") or {}
        final.update(descriptions)

    validated = {}
    for draft in drafts:
        name = draft["name"]
        desc = (final.get(name) or "").strip()
        if len(desc) >= MIN_DESCRIPTION_LEN:
            validated[name] = desc
            continue

        print(f"    Description missing/short for '{name}', retrying individually...")
        retry_prompt = DESCRIBE_SINGLE_PROMPT.format(
            name=name, reading_titles=titles_block(draft["readings"], readings_by_id),
        )
        retry_text, _ = call_claude(client, retry_prompt, max_tokens=STAGE25_SINGLE_MAX_TOKENS)
        retry_text = retry_text.strip()
        if len(retry_text) >= MIN_DESCRIPTION_LEN:
            validated[name] = retry_text
        else:
            titles = [readings_by_id[rid]["title"] for rid in draft["readings"] if rid in readings_by_id]
            stub = ("[AUTO-GENERATED - NEEDS REVIEW] Domain grouping readings including: "
                    + "; ".join(titles[:3]) + ("..." if len(titles) > 3 else "."))
            print(f"    Individual retry also failed for '{name}' -- using auto-generated stub")
            validated[name] = stub

    save_stage25_cache(output_dir, area["id"], validated)
    return validated


def finalize_area_case_studies(area, drafts, descriptions, readings_by_id, topic_order, axis_order, valid_areas):
    case_studies = []
    for draft in drafts:
        case_studies.append(finalize_case_study(
            f"{area['id']}_{slugify(draft['name'])}", draft["name"], [area["id"]],
            descriptions.get(draft["name"], ""), draft["readings"], draft["background_concepts"],
            readings_by_id, topic_order, axis_order, valid_areas,
        ))
    return case_studies


def process_area(client, area, readings, readings_by_id, output_dir, chunk_size, force,
                 topic_order, axis_order, valid_areas):
    area_readings = readings_for_area(readings, area["id"])
    print(f"Area {area['id']}: {len(area_readings)} readings")
    if not area_readings:
        save_checkpoint(output_dir, area["id"], [])
        return []

    domain_names = stage1_discover_domains(
        client, area, area_readings, output_dir, chunk_size, force,
    )
    print(f"  -> {len(domain_names)} candidate domains")
    assignments = stage2_assign_readings(
        client, area, domain_names, area_readings, output_dir, chunk_size, force,
    )
    drafts = build_drafts(domain_names, assignments)
    descriptions = write_domain_descriptions(
        client, area, drafts, readings_by_id, output_dir, force,
    )
    area_case_studies = finalize_area_case_studies(
        area, drafts, descriptions, readings_by_id, topic_order, axis_order, valid_areas,
    )
    save_checkpoint(output_dir, area["id"], area_case_studies)
    return area_case_studies


# ---------------- finalize ----------------

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


# ---------------- stage 3: cross-area dedup/merge ----------------

def cross_area_merge(case_studies, overlap_threshold=0.5):
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


# ---------------- stage 4: reconciliation ----------------

def reconcile_uncovered(client, readings, case_studies, readings_by_id, topic_order, axis_order,
                        valid_areas, chunk_size):
    covered = {rid for cs in case_studies for rid in cs["readings"]}
    uncovered = [r for r in readings if not r.get("area_agnostic") and r["areas"] and r["id"] not in covered]
    if not uncovered:
        print("Coverage diff: nothing uncovered.")
        return case_studies

    print(f"Coverage diff: {len(uncovered)} readings uncovered, reconciling in chunks of {chunk_size}...")
    existing_dump = "\n".join(f"{cs['id']}: {cs['name']} (areas={cs['areas']})" for cs in case_studies)

    for chunk in chunk_list(uncovered, chunk_size):
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
        text, truncated = call_claude(client, prompt, max_tokens=RECONCILE_MAX_TOKENS)
        if truncated:
            print("    WARNING: reconciliation response truncated")
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--framework", default=DEFAULT_FRAMEWORK)
    parser.add_argument("--readings", default=DEFAULT_READINGS)
    parser.add_argument("--out", default=DEFAULT_OUT, help="final examples.json output path")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help="directory for stage1/, stage2/, checkpoints/ caches")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"readings per API call for stage 1/2 (default {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print corpus stats and dump-size analysis; no API calls")
    parser.add_argument("--force", action="store_true",
                        help="ignore cached stage1/stage2/checkpoint files and re-run API calls")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run(args.framework, args.readings, args.chunk_size, args.output_dir)
        return

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY not set. Add it to .env (see .env.example) or export it in your shell."
        )

    import anthropic

    client = anthropic.Anthropic()
    framework, readings, readings_by_id = load_inputs(args.framework, args.readings)
    topic_order = topic_order_ids(framework)
    axis_order = [a["id"] for a in framework["cross_cutting_axes"]]
    valid_areas = {a["id"] for a in framework["areas"]}

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"Output dir: {args.output_dir}  chunk_size={args.chunk_size}")

    all_case_studies = []
    for area in framework["areas"]:
        cached = None if args.force else load_checkpoint(args.output_dir, area["id"])
        if cached is not None and checkpoint_is_complete(args.output_dir, area["id"], cached):
            print(f"Area {area['id']}: using checkpoint ({len(cached)} case studies)")
            all_case_studies.extend(cached)
            continue

        if cached is not None:
            print(f"Area {area['id']}: checkpoint lacks stage 2.5 -- rebuilding descriptions from caches")

        area_readings = readings_for_area(readings, area["id"])
        if cached is not None and not args.force:
            drafts = load_drafts_from_stage_caches(
                area, area_readings, readings_by_id, args.output_dir, args.chunk_size,
            )
            if drafts is not None:
                print(f"Area {area['id']}: stage 2.5 from cached stage1/2 ({len(drafts)} domains)")
                descriptions = write_domain_descriptions(
                    client, area, drafts, readings_by_id, args.output_dir, args.force,
                )
                area_case_studies = finalize_area_case_studies(
                    area, drafts, descriptions, readings_by_id, topic_order, axis_order, valid_areas,
                )
                save_checkpoint(args.output_dir, area["id"], area_case_studies)
                all_case_studies.extend(area_case_studies)
                continue

        area_case_studies = process_area(
            client, area, readings, readings_by_id, args.output_dir, args.chunk_size, args.force,
            topic_order, axis_order, valid_areas,
        )
        all_case_studies.extend(area_case_studies)

    print(f"\n{len(all_case_studies)} case studies before cross-area merge")
    all_case_studies = cross_area_merge(all_case_studies)
    all_case_studies = recompute_coverage(all_case_studies, readings_by_id, topic_order, axis_order)
    print(f"{len(all_case_studies)} case studies after cross-area merge")

    all_case_studies = reconcile_uncovered(
        client, readings, all_case_studies, readings_by_id, topic_order, axis_order, valid_areas,
        args.chunk_size,
    )

    covered = {rid for cs in all_case_studies for rid in cs["readings"]}
    metadata = {
        "purpose": "Domain-level case studies within each framework area, generated via the "
                   "ictd-case-study-generation skill (v2: stage1 names + stage2 assignments + "
                   "stage2.5 grounded descriptions + cross-area merge) using the Claude API.",
        "schema_note": "topics_covered/cross_cutting_axes are auto-derived, not independently "
                       "curated by the model. background_concepts URLs were grounded via web "
                       "search but should still be spot-checked before publishing.",
        "total_case_studies": len(all_case_studies),
        "readings_referenced": len(covered),
        "readings_total_in_corpus": len(readings),
        "coverage_note": "Gap is expected to be almost entirely area_agnostic=true readings.",
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"metadata": metadata, "case_studies": all_case_studies}, f, indent=2)

    print(f"\nDone. {len(all_case_studies)} case studies, {len(covered)}/{len(readings)} "
          f"readings referenced. Written to {args.out}")
    print("Recommended: run the skill's step-5 validation checks and spot-check "
          "background_concepts URLs before treating this as final.")


if __name__ == "__main__":
    main()
