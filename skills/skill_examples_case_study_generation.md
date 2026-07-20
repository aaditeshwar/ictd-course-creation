---
name: ictd-case-study-generation
description: >
  Generate a domain-level "examples.json" of case studies from an existing readings.json +
  framework.json pair, for an ICTD-style (or similarly area x topic structured) course. Use
  this when the reading list has grown large enough (100+ readings) that individual readings
  are hard to browse directly, and you want to group them into recurring real-world domains
  (e.g. "voice-based agricultural extension", "REDD+ forest carbon offsets") that a single
  class or lecture could be built around. Also identifies, per case study, the domain-specific
  background concepts the readings assume but don't teach (e.g. aquifer basics and specific
  yield/hydraulic conductivity for a groundwater case study), and suggests readymade
  introductory learning material for each. Trigger this skill whenever asked to build, refresh,
  or extend an "examples" / "case studies" file from a reading list that's already tagged with
  areas/topics/axes.
---

# ICTD Case Study Generation

## What a "case study" is here (and isn't)

A case study is a **domain**, not a project: a recurring pattern of similar
interventions/research within one area, e.g. "voice-based community media platforms" or
"forest carbon MRV and offset integrity" -- not "the Gram Vaani paper" or "the REDD+ paper."
One area typically contains multiple case studies (governance had 6 in the last run; water
security had 6). A case study should ideally span **multiple topics** (problem_discovery
through operations_scale), because that's what makes it useful for building a class or lecture
around: readings that let you walk the full arc from "why does this problem matter" to "did
this actually work at scale."

Reject candidate groupings that are really just "papers by the same author" or "papers with a
similar title" if they don't share a real-world domain. Two satellite-ML papers on unrelated
subjects (crop yield vs. flood mapping) are not the same case study just because they're both
`cs_fundamentals`.

## Prerequisites

You need, at minimum:
- `framework.json` with a populated `areas`, `topics` (with `sequence` numbers), and
  `cross_cutting_axes` list, each with an `id`.
- `readings.json` with every reading tagged `areas: [ids]`, `topics: [ids]`,
  `cross_cutting_axes: [ids]`, and an `area_agnostic: bool` flag. If readings aren't tagged
  yet, tag them first -- this skill assumes tagging is already done and just re-groups it.

## Procedure

### 1. Dump readings grouped by area, don't try to hold 150+ readings in your head

Write a small script that groups `readings.json` by `area`, printing `[id] title | topics=[...] axes=[...]`
for each. Do this once, up front, and actually read through the whole dump area by area rather
than sampling. The domain clusters are usually visible just from title text once readings are
sitting next to their siblings -- you don't need to read abstracts to spot "these five are all
about IVR-based farmer advisories."

```python
from collections import defaultdict
by_area = defaultdict(list)
for r in readings:
    for a in (r['areas'] or ['(area_agnostic/none)']):
        by_area[a].append((r['id'], r['title'][:75], r['topics'], r['cross_cutting_axes']))
```

### 2. Draft domain groupings per area, aiming for topic diversity within each

For each area, look for clusters of 3+ readings that share a real-world subject. Prefer
groupings that already span multiple topics over ones that are all the same topic (an
all-`cs_fundamentals` cluster is a valid case study, but a cluster spanning
problem_discovery + ethnographic_design + sociotechnical_dynamics + impact_evaluation makes a
much better lecture arc). Don't force every reading into a case study -- some will genuinely be
one-offs; leave them out rather than inventing a weak grouping.

**Deliberately exclude `area_agnostic: true` readings from area-based case studies.** These are
general theory/methodology readings (Sen, Piketty, Schumacher, etc.) that don't belong to one
area's domain by design -- they're already organized separately via
`framework.json`'s `area_agnostic_topic_vector` (see the framework-building skill, if it
exists, or build one topic-methodology entry per topic with its own curated example readings).
Forcing them into an area's case study just to raise a coverage number produces a worse map,
not a better one.

Cross-area case studies are fine and expected (e.g. an MGNREGA case study naturally spans
labour + forests_restoration + water_security). List the primary area first in the `areas`
array; that's what determines which area section it displays under.

### 3. Identify the domain prerequisites the readings assume but don't teach

Most readings in a case study assume the reader already has some baseline technical or
domain vocabulary, and will only make partial sense without it. E.g. the water_security case
studies reference GRACE-based storage estimation, Granger causality on groundwater time series,
and specific yield/hydraulic conductivity without explaining what an aquifer even is or how
water moves through one; the forest carbon case studies assume familiarity with what "canopy
height" or "biomass" estimation means physically, not just as an ML target variable. A student
reading only the case study's papers will follow the *methods* but miss the *physical/domain
reality* the methods are approximating -- and won't be able to sanity-check whether a result is
plausible.

For each case study, do a second, narrower pass: read through its readings' titles/abstracts
specifically looking for **domain jargon or a measured quantity that the readings use but don't
define** (a metric, a physical process, a named framework/theory, a piece of institutional
machinery). List these as `background_concepts`. For each concept, search for and suggest one
or two pieces of **readymade, freely accessible learning material** that teaches it at an
introductory level -- not another research paper, but the kind of thing you'd assign *before*
the case study's readings: a textbook chapter, a university lecture-note PDF, an NPTEL/Coursera
module, a well-regarded explainer/primer, or a technical agency's own plain-language guide (e.g.
USGS/CGWB water-cycle explainers, IPCC primers, FAO manuals). Prefer sources that are: (a) short
enough to assign as pre-reading (not another full textbook), (b) freely accessible without a
paywall, and (c) written for someone learning the concept for the first time, not for
practitioners already fluent in it.

Examples of the level of specificity to aim for (don't just say "students should learn about
water" -- name the actual gap):

- Case study: groundwater depletion sensing → concepts: *aquifers and groundwater storage*,
  *specific yield*, *hydraulic conductivity and transmissivity*, *GRACE satellite gravimetry
  basics* → suggest e.g. a USGS "Groundwater and the Water Cycle" primer, an NPTEL groundwater
  hydrology lecture, and a short GRACE-mission explainer from NASA/JPL.
- Case study: forest carbon MRV → concepts: *what "canopy height" and "aboveground biomass"
  physically are*, *the basic carbon cycle*, *what LiDAR/GEDI actually measures vs. estimates* →
  suggest a forestry-department biomass-estimation primer and a GEDI mission explainer.
- Case study: e-governance/bureaucratic ICT → concepts here are more institutional than
  physical: *what MGNREGA/NREGA actually is as a scheme*, *how India's RTI Act and social
  audits work procedurally* → suggest the relevant government scheme FAQ/handbook and a
  civil-society primer (e.g. MKSS's own materials) rather than a satellite-data explainer, since
  "domain prerequisite" means whatever the readings assume, which varies a lot by area.

Not every case study needs this -- some (e.g. a case study built entirely from readable
narrative nonfiction, like the water-security "climate-vulnerable landscapes" case study) may
have no real jargon gap. Leave `background_concepts` as an empty list rather than padding it.

`background_concepts` is per-case-study **supplementary** material -- it does not get folded
into `readings`, does not affect `topics_covered`/`cross_cutting_axes` derivation (step 4 below
still only looks at `readings`), and is not itself subject to the areas/topics/axes controlled
vocabulary, since it's deliberately reaching outside the curated reading list.

### 4. Auto-derive topic/axis coverage from constituent readings -- never hand-type it

This is the single most important implementation detail. Write the builder so that
`topics_covered` and `cross_cutting_axes` on each case study are computed as the **union of
tags across its member readings**, not independently written by you:

```python
def build_case_study(id_, name, areas, description, reading_ids, readings_by_id, background_concepts=None):
    topics, axes = set(), set()
    for rid in reading_ids:
        r = readings_by_id[rid]  # KeyError here is a feature -- it catches typo'd ids immediately
        topics.update(r['topics'])
        axes.update(r['cross_cutting_axes'])
    topic_order = [t['id'] for t in sorted(framework['topics'], key=lambda t: t['sequence'])]
    axis_order = [a['id'] for a in framework['cross_cutting_axes']]
    return {
        "id": id_, "name": name, "areas": areas, "description": description,
        "topics_covered": [t for t in topic_order if t in topics],
        "cross_cutting_axes": [a for a in axis_order if a in axes],
        "readings": reading_ids,
        "background_concepts": background_concepts or [],
    }
```

This guarantees the file can never drift out of sync with `readings.json`'s own tagging --
if a reading's topics get corrected later, regenerating `examples.json` picks that up for free.
It also means you (the model or person building this) only have to supply the things that
actually require judgment: which readings belong together, a 2-3 sentence description of the
domain, and the background concepts from step 3. Everything structural is derived.

### 5. Validate against the framework's controlled vocabulary before calling it done

```python
valid_areas = {a['id'] for a in framework['areas']}
valid_topics = {t['id'] for t in framework['topics']}
valid_axes = {a['id'] for a in framework['cross_cutting_axes']}
# assert every case study's areas/topics_covered/cross_cutting_axes are subsets of these
```
Also check: unique case study ids, no case study with zero readings, and no `KeyError`s
during the build (any reading id you typed that doesn't exist in `readings.json`).

### 6. Diff coverage against the full corpus, and reconcile stragglers -- don't skip this

After building, compute `readings_referenced = union of all case studies' reading ids` and
diff it against all of `readings.json`. You will find two kinds of leftovers:
- **Expected**: `area_agnostic: true` readings (leave these out, per step 2).
- **Unexpected**: area-tagged readings that just didn't get noticed during the manual
  clustering pass in step 2 (this happened in practice: 5 readings were missed on the first
  pass, including a paper found only because it shared a governance tag with an existing case
  study). For each unexpected leftover, look at its title/area/topic and either fold it into an
  existing case study (most common outcome) or, if there are several orphans on the same
  subject, spin up one more small case study.

Record the final "N case studies, M/Total readings referenced" numbers in the output file's own
metadata, along with a one-line explanation of why the gap is nonzero (which should just be "the
area-agnostic readings"). This makes the intentional exclusion legible to whoever reads the file
later instead of looking like an oversight.

## At scale (1000+ readings): the single-call-per-area approach breaks down

Everything above describes doing this manually (a human, or a model in an interactive chat,
reading through the dumps and drafting groupings by hand) or via one API call per area. That
works fine up to roughly **150 readings per area**. Past that, a single call asked to discover
domains, name them, assign every reading, and research background concepts all at once tends to
either get truncated mid-JSON (if `max_tokens` is too low for how much output a much larger area
now needs) or silently do a shallower clustering job than a careful human re-read would (a known
weak spot of single-pass attention over very long flat lists, not a context-window-size problem
-- the tokens fit, the reasoning quality per item degrades).

`generate_examples_via_api.py` implements a **two-stage, chunked, checkpointed** version for
this regime:

1. **Stage 1 (domain discovery)**: one call per area (or per chunk, if the area exceeds
   `CHUNK_SIZE` readings) asking only for candidate domain *names and descriptions* -- no reading
   IDs yet. A smaller, narrower task per call is more reliable than asking for everything at once.
2. **Stage 2 (reading assignment)**: given the domain names from stage 1, a second call (again
   chunked if needed) assigns specific reading IDs to each named domain, and does the
   background-concepts research from step 3 above. Splitting this from stage 1 means the model
   isn't simultaneously inventing domain boundaries and trying to remember which reading IDs it
   already committed to a domain -- two easier tasks beat one harder one.
3. **Stage 3 (cross-area merge -- NEW, and not optional at this scale)**: because stage 1 runs
   independently per area, a genuinely cross-area domain (the MGNREGA example: tagged
   `areas: [forests_restoration, labour]` at the reading level) will very likely get
   **independently rediscovered** once under each area it touches, as two near-duplicate
   proposals with overlapping reading sets. This is not a new failure mode introduced by
   chunking -- it existed in the single-call-per-area version too -- but a human doing the whole
   exercise in one sitting (as in the original 259-reading run) resolves it by eye without
   noticing they're doing so. At scale it needs an explicit pass: compute reading-ID-overlap
   (Jaccard) between every pair of proposed case studies, and merge any pair above a threshold
   (`0.5` by default) into one case study with the union of readings and areas. Verify a sample
   of what got merged -- a coincidentally similar reading set between two genuinely distinct
   domains is possible, if rare, and the merge is silent by default (only logged to stdout, not
   flagged in the output file).
4. Chunk size, checkpointing, and the reconciliation pass (skill step 6) all follow the same
   chunking logic once an area or the uncovered-readings list gets large.

**Practical guidance**: don't treat 150/area as a hard cliff -- it's a "start watching for
truncation warnings and shallow clustering" threshold, not a switch that flips. If you're running
this on a corpus where some areas are small (health at 90 readings) and others are huge
(governance at 400), it's fine that only the huge ones actually chunk; `CHUNK_SIZE` chunking
kicks in per-area automatically based on that area's own reading count.

After a run at this scale, **do the coverage-diff eyeballing from step 6 more carefully than
usual**, and specifically skim the "Merged N cross-area duplicates" log lines from stage 3 --
that log is your only visibility into what the automated merge decided, and it's worth
overriding by hand if two merged case studies don't actually belong together.

## Output schema

```json
{
  "metadata": {
    "purpose": "...",
    "schema_note": "topics_covered/cross_cutting_axes are auto-derived, not independently curated",
    "date_compiled": "...",
    "total_case_studies": N,
    "readings_referenced": M,
    "readings_total_in_corpus": T,
    "coverage_note": "why M < T is expected"
  },
  "case_studies": [
    {
      "id": "snake_case_short_id",
      "name": "Human-readable domain name",
      "areas": ["primary_area_id", "secondary_area_id_if_any"],
      "description": "2-3 sentences: what this domain is and why it's grouped together",
      "topics_covered": ["problem_discovery", "cs_fundamentals", "..."],
      "cross_cutting_axes": ["climate_change", "..."],
      "readings": ["reading_id_1", "reading_id_2", "..."],
      "background_concepts": [
        {
          "concept": "Short name of the prerequisite concept/metric/institution",
          "why_needed": "One sentence: which of this case study's readings assumes this, and how",
          "suggested_resources": [
            {"title": "...", "url": "...", "type": "primer | lecture_notes | course_module | agency_guide"}
          ]
        }
      ]
    }
  ]
}
```

## Common mistakes to avoid (from experience)

- **Don't split by topic instead of by domain.** "All the cs_fundamentals readings in
  agriculture" is not a case study; it's a topic filter. A case study is defined by its
  real-world subject matter, and different case studies within the same area will each have
  their own topic spread.
- **Don't let case-study count per area become a proxy for area richness you're trying to
  hit.** Some areas will legitimately have 2 case studies (education, wildlife_conservation in
  the reference run) and others 6 (governance, water_security) -- that reflects the actual
  reading list's depth, not a target to equalize toward.
- **Don't hand-write topics_covered/cross_cutting_axes "because it's faster."** It isn't faster
  once you account for the silent drift bugs it causes the first time someone corrects a
  reading's tags without remembering to also update every case study that reading appears in.
- **Don't let `background_concepts` turn into a generic "further reading" dump.** Every entry
  should trace back to a specific term/metric that specific readings in the case study actually
  use without defining -- if you can't point to which reading assumes it, it doesn't belong here.
- **At 1000+ reading scale, don't skip the cross-area merge pass (stage 3 in the API version).**
  Without it you'll get duplicate near-identical case studies under different areas for anything
  genuinely cross-area, and the duplication compounds every time readings.json grows further.
- **Do re-run this whenever readings.json changes substantially** (a new venue's papers get
  merged in, a batch of corrections lands) -- case studies that were thin before may now have
  enough readings to justify a fuller entry, and new domains may have appeared.

