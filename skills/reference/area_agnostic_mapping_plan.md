# Area-Agnostic Reading Prioritization & Case-Study Mapping: Implementation Plan

Plan only -- no code yet. Covers rebuilding `area_agnostic_topic_vector` from ground truth
(Tier A) and the nested-chunked relevance-scoring pipeline that maps low-breadth area-agnostic
readings onto case studies (Tier B), at the confirmed scale: 1,153 readings, 299 area_agnostic,
147 case studies.

## 1. Tier split (recap, now finalized)

- **Tier A** (breadth >= 2 topics, OR flagged as a book via the `"This is a book. "` notes
  prefix): 25 readings. Goes straight into a rebuilt `area_agnostic_topic_vector` -- **no
  relevance-scoring pass**, confirmed.
- **Tier B** (breadth <= 1, non-book): everything else (274 readings before the two manual
  fixes; recomputed fresh at runtime against whatever `readings.json` is current, so the exact
  count may shift slightly once your two edited readings get their `topics` tag and move from
  "unclassifiable" into Tier B). Goes through nested-chunked (reading, case_study) relevance
  scoring.
- Breadth is computed directly as `len(reading["topics"])` from `readings.json` -- the existing
  `area_agnostic_topic_vector` is never consulted for this, since it's confirmed stale (27 of
  299 present).

## 2. New file: `skills/rebuild_area_agnostic_vector.py` (Tier A, mechanical, no LLM)

Pure data transformation, no model calls needed:

1. Load `readings.json`, filter to `area_agnostic: true`.
2. Compute Tier A membership: `len(topics) >= 2 or notes.startswith("This is a book.")`.
3. For each Tier A reading, add its id to **every topic in its own `topics` array** in
   `area_agnostic_topic_vector` (a breadth-4 reading appears under all 4 of its topics' example
   lists, same convention as the original hand-curated version).
4. **Preserve existing `methodology_description` text per topic** -- these were hand-written and
   don't need regenerating, only `example_readings` membership changes.
5. Report a diff before writing: which reading ids are newly added vs. the current 27, and
   whether any of the current 27 fall OUT of Tier A under the recomputed rule (e.g. if a
   previously-curated reading's `topics` array has since been trimmed to 1) -- surface this
   explicitly rather than silently dropping something a human deliberately chose before.
6. Write the updated `framework.json`.

No chunking, no backend selection, no caching needed -- this is a same-second script.

## 3. New file: `skills/score_area_agnostic_relevance.py` (Tier B, nested-chunked LLM scoring)

### 3.1 Constants (as requested, named and changeable, not buried in logic)

```python
READING_CHUNK_SIZE = 10       # readings per call
CASE_STUDY_CHUNK_SIZE = 10    # candidate case studies per call
```

### 3.2 Topic-scoped candidate generation (cheap pre-filter, no LLM)

For each topic, build:
- `readings_for_topic`: Tier B readings whose `topics` includes this topic
- `case_studies_for_topic`: case studies whose `topics_covered` includes this topic

Only readings and case studies that share a topic are ever considered together -- this is what
keeps the pairwise space bounded instead of the raw 274 x 147 = 40,278.

### 3.3 Nested chunking and call shape

For each topic, chunk `readings_for_topic` into batches of `READING_CHUNK_SIZE` and
`case_studies_for_topic` into batches of `CASE_STUDY_CHUNK_SIZE`. One call per
(reading-batch, case-study-batch) pair, i.e. `ceil(R/10) * ceil(C/10)` calls per topic.

Each call sends: the `READING_CHUNK_SIZE` readings' titles + abstracts, and the
`CASE_STUDY_CHUNK_SIZE` case studies' names + descriptions (plus, for grounding, a short sample
of `key_facts` from that case study's own readings for this topic, so the model is judging
against *what this case study's topic slot actually contains*, not just its one-line
description). Asks for a full relevance grid back: every (reading, case_study) cell in this
batch gets a score.

Prompt output shape per cell:
```json
{"reading_id": "...", "case_study_id": "...", "relevance_score": 1-5,
 "relevant_topic": "<topic id>", "relevance_note": "one sentence, specific"}
```
`relevance_score` of 1 is a legitimate, expected output (most cells in a chunk will likely score
low) -- **the scorer records every cell, not just plausible-looking ones**. Thresholding is a
separate, later, offline step (\u00a75), not baked into this pass.

### 3.4 Caching / resumability

Same convention as the rest of this pipeline (`topic_content_extractor.py`'s map-phase cache
pattern): cache key is `(topic, reading_chunk_ids, case_study_chunk_ids, backend, model)`,
written to `area_agnostic_relevance_scores.json` incrementally (after each chunk pair, not just
at the end), so an interrupted run resumes rather than restarting.

### 3.5 Backend

Single `--backend` flag (default from `ALIGNMENT_BACKEND`/env, same resolution pattern as
elsewhere) -- no map/reduce split needed here since there's only one LLM call type in this
script, unlike `topic_content_extractor.py`.

### 3.6 Call volume estimate (rough, to sanity-check before a full run)

Depends heavily on how readings/case studies distribute across the 6 topics -- `problem_discovery`
will dominate given the breadth data already seen (most single-topic area-agnostic readings were
`problem_discovery`). Worst-case sanity check: if one topic alone has ~150 candidate readings and
~80 candidate case studies, that's `ceil(150/10) * ceil(80/10) = 15 * 8 = 120` calls for that
topic alone. Recommend running one topic first as a dry run to get a real per-call timing number
on qwen2.5:14b before estimating total wall-clock time across all 6 topics.

## 4. New file: `skills/apply_area_agnostic_threshold.py` (offline, no LLM, the actual dry-run tool)

This is the script built specifically for your "I will do some dry runs to finalize this"
requirement -- reads `area_agnostic_relevance_scores.json` (already fully computed, \u00a73) and:

```
python skills/apply_area_agnostic_threshold.py --min-score 4 --max-case-studies-per-reading 3
```

- Filters all scored pairs to `relevance_score >= --min-score`.
- Per reading, keeps only the top `--max-case-studies-per-reading` scoring pairs (ties broken by
  score, then arbitrarily -- flagged in output if a tie-break happened, in case that matters for
  review).
- Writes the final `related_area_agnostic_readings` field onto each affected case study in
  `examples.json` -- **a new, separate field, sibling to `background_concepts`, not merged into
  `readings`** (so it doesn't disturb `topics_covered`/`cross_cutting_axes` auto-derivation, per
  the design agreed two turns ago):
  ```json
  "related_area_agnostic_readings": [
    {"reading_id": "...", "relevant_topic": "...", "relevance_score": 4,
     "relevance_note": "..."}
  ]
  ```
- Re-running this script with different flags is instant (no LLM calls) and always starts fresh
  from the same raw scores file -- exactly the fast dry-run loop you described. Running it twice
  with different thresholds is how you'd compare, e.g., "min-score 3, cap 2" vs. "min-score 4,
  cap 3" side by side before committing to one.

## 5. Process order

1. `rebuild_area_agnostic_vector.py` (Tier A -- instant, run first, no dependencies)
2. `score_area_agnostic_relevance.py` (Tier B -- the expensive step, run once; recommend one
   topic as a dry run first per \u00a73.6)
3. `apply_area_agnostic_threshold.py` (run as many times as needed while you tune the threshold
   -- this is the actual "dry run" loop)

## 6. Open items / risks flagged honestly

- **The two edited readings**: once their `topics` tag is set, they'll be picked up automatically
  by the tier-split logic at runtime -- no special-casing needed in the code, confirming this
  wasn't worth blocking the plan on.
- **Topic imbalance across the 6 topics is unverified** -- `problem_discovery` is very likely to
  dominate both readings and case studies, which could make its chunk count disproportionately
  large. Worth checking the actual per-topic counts before committing to a full run, not just
  assuming CHUNK_SIZE=10 is right for every topic equally.
- **Grounding the case-study side of each prompt in real `key_facts`** (not just the one-line
  case study description) adds real prompt length per case-study slot -- if this pushes chunks of
  10 case studies past what qwen2.5:14b handles comfortably, the fix is lowering
  `CASE_STUDY_CHUNK_SIZE` (already a named constant, not a code change) rather than redesigning.
- **A reading capped at `--max-case-studies-per-reading` in \u00a74 doesn't lose its lower-ranked
  matches** -- they stay in the raw scores file, just don't make it into `examples.json` at the
  current threshold. Re-running \u00a74 with a higher cap later is non-destructive.

## 7. Acceptance checklist, once built

- [ ] Tier A/B split recomputed correctly against a fresh `readings.json` (spot-check the two
      newly-tagged readings land in Tier B, not Tier A, given breadth=1)
- [ ] `rebuild_area_agnostic_vector.py` reports its diff (added/removed reading ids) before
      writing, doesn't silently overwrite
- [ ] `score_area_agnostic_relevance.py` resumes correctly after an interrupted run (kill it
      mid-topic, restart, confirm no duplicate calls for already-cached chunk pairs)
- [ ] Raw scores file contains low scores too, not just plausible matches (spot check a chunk's
      full output, not just the top-scoring cells)
- [ ] `apply_area_agnostic_threshold.py` run twice with different flags produces different
      `related_area_agnostic_readings` outputs without any new LLM calls
- [ ] `related_area_agnostic_readings` never appears inside `readings` or affects
      `topics_covered`/`cross_cutting_axes` on any case study
- [ ] A reading appearing in multiple case studies (once thresholds are set) is expected
      behavior, not a bug -- confirm the cap flag is the only thing limiting this, not an
      accidental dedup somewhere in the pipeline
