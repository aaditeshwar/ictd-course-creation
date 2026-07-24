# Lecture-Prep Pipeline v3: Targeted Appendix Generation

Implementation plan only — no code yet. Covers the fix for the appendix quality problem
(reads like a paper summary, not organized around mechanisms) by splitting reduce into two
passes and driving the second pass from the deck itself rather than running it blind.

## 1. Diagnosis recap (why this change is needed)

The current single reduce call asks for `key_facts`/`mechanism`/`data_points`/`appendix`
together, with the appendix instruction being an open-ended "organize with `##` subheadings as
needed." Given a rich candidate set from the map phase, the model's natural interpretation was
to reconstruct something close to the paper's own structure (Introduction → Methods → Findings →
Conclusion) — comprehensive by default, not targeted. Worse, this happens **before the deck
exists**, so the appendix has no visibility into what a lecture built from the slide-facts
manifest will actually need elaborated. Any overlap between what got written and what the deck
needs is coincidental.

## 2. New shape

```
topic_content_extractor.py           (TRIMMED — see §3)
        |
run_lecture_prep.py                  (consolidates slide manifest, as before, but no longer
        |                             produces appendix.md at the end)
        |
        v
[Claude builds slides from lecture_prep_manifest.json, produces deck + outline.md
 with a structured "Appendix Requests" block]
        |
        v
appendix_writer.py                   (NEW — see §4, driven by outline.md's requests)
        |
        v
appendix.md                          (now targeted, generated on demand per deck, not
                                       automatically for every reading x topic pair)
```

The key structural change: **appendix generation moves from an automatic, blind pipeline step to
an on-demand step driven by the actual lecture deck.** `run_lecture_prep.py` no longer produces
`appendix.md` at all — it only produces the slide-facts manifest. `appendix.md` is generated
afterward, once, per deck, from whatever the deck-building process actually flagged.

## 3. Changed file: `skills/topic_content_extractor.py`

- `REDUCE_PROMPT` drops the `appendix` field entirely — output shape becomes just
  `{"key_facts": [...], "mechanism": "...", "data_points": [...]}`.
- `run_reduce_phase()` / `reduce_cache_valid()` / `topic_content.json` schema all lose the
  `appendix` key correspondingly. No other logic changes — caching, map phase, backend
  selection, all identical to v2.
- This makes reduce-1 strictly cheaper per call (shorter expected output, smaller `max_tokens`
  budget needed — can likely drop `REDUCE_MAX_TOKENS` from 4000 back down toward map-phase
  territory, worth tuning empirically rather than guessing a number here).
- **Backward compatibility note**: any existing `topic_content.json` cache files from v2 runs
  will have a stale `appendix` key sitting in cached entries. Harmless to leave (it'll just be
  ignored by the trimmed schema going forward), but `--force-reduce` on existing case studies
  will naturally clean it up as caches get regenerated. Not worth writing a migration script for
  one stray key.

## 4. New file: `skills/appendix_writer.py`

### 4.1 Input
A structured "Appendix Requests" block, parsed out of the deck-building outline markdown I
produce. Format (agreed schema):
```markdown
## Appendix Requests
- reading: <reading_id>
  topic: <topic_id>
  ask: "<specific, narrow question — not 'more about this paper'>"
```
Multiple asks can target the same `(reading, topic)` pair if a deck needs more than one distinct
elaboration from it — the writer treats each list entry as an independent request, not
deduplicated by `(reading, topic)` alone.

### 4.2 Processing
For each request:
- Look up the reading's cached map-phase candidates from `map_candidates.json` (**no
  re-extraction, no re-reading the PDF** — this is the efficiency win from keeping map/reduce
  cache separate from the start).
- If no map cache exists for that reading (e.g. it was abstract-only, per v2's fallback path),
  fall back to the reading's abstract as the source material, same degradation path
  `topic_content_extractor.py` already uses.
- Build a **constrained** prompt (see §4.3) and call the LLM (reuse `call_llm`/backend-resolution
  helpers from `topic_content_extractor.py` — import them rather than duplicating).

### 4.3 Prompt constraints (the actual quality fix, independent of the split)
The new appendix prompt must, unlike the old open-ended one:
- Open by directly answering the specific `ask`, not by introducing the paper.
- Organize around **mechanism → criteria/thresholds/formulas (if any) → concrete
  numbers/examples**, in that order, using those (or closely equivalent) as the actual
  subheading structure — not paper-shaped sections.
- **Explicitly prohibit** generic academic-summary headers: no "Introduction," "Background,"
  "Overview," "Conclusion," "Findings" as section names. If context genuinely matters, it goes
  in a line or two of lead-in prose before the first real subheading, not its own section.
- Still target the same 150–1500 word range as before, still scale to what the source material
  actually supports (a narrow, well-answerable `ask` might only need 200 words even with plenty
  of candidate material available — length follows the ask's scope, not the candidate volume).
- Liberal quoting still applies (course-internal document, same as v2's rule) — unchanged.

### 4.4 Output
`appendix_content.json`, keyed by request rather than by `(reading, topic)` alone (since a deck
can generate more than one request against the same pair):
```json
[
  {
    "reading": "...", "topic": "...", "ask": "...",
    "content": "...",
    "backend": "...", "model": "...",
    "source": "map_candidates | abstract_fallback"
  }
]
```
Caching: keyed on a hash of `(reading, topic, ask text)` — if the same outline is re-run
unchanged, skip regenerating; if the `ask` text changes (I refine the request), it's treated as a
new request rather than silently reusing a stale answer. `--force` flag to bypass, same
convention as the rest of this pipeline.

### 4.5 Assembly into `appendix.md`
Moves out of `run_lecture_prep.py` (§5) into `appendix_writer.py` itself, since it now runs at a
different point in the workflow. Grouping logic is otherwise identical to v2's
`build_appendix_markdown()`: by topic first (framework sequence order), reading second, within
each topic only including requests that were actually asked (which, by construction, is now
*all* of them — there's no "thin/empty" case to filter anymore, since every entry in
`appendix_content.json` exists because something specifically asked for it).

## 5. Changed file: `skills/run_lecture_prep.py`

- Remove the `appendix.md` assembly step and the `build_appendix_markdown()` function entirely
  — this logic moves to `appendix_writer.py` (§4.5).
- Remove `appendix` handling from the `lecture_prep_manifest.json` consolidation (it was already
  excluded from that file in v2; no change needed there beyond confirming it stays excluded).
- Closing message updated: no longer mentions `appendix.md` as an automatic output — mentions
  that extended notes are generated separately, on demand, via `appendix_writer.py` once a deck
  and its outline exist.
- Everything else (resolve/download, PDF extraction, alignment scoring, topic-content reduce-1,
  slide-facts manifest consolidation) is unchanged.

## 6. Process change: how the "Appendix Requests" block gets produced

This isn't a script — it's a convention for how I build decks going forward, formalized here so
it's consistent across sessions rather than reinvented each time:

- Whenever building a deck, every slide-level "Appendix:" note I currently already write (per
  `skill_lecture_deck_building.md`'s existing "Appendix pointers" section) additionally gets
  captured, verbatim, into the outline markdown's `## Appendix Requests` block using the schema
  in §4.1.
- The `ask` text should be the same specific, narrow phrasing I already use in-slide (e.g. *"full
  5-step method detail, including how the Vulnerability Code is computed"*) — not rewritten to be
  more general. Specificity here is what makes §4.3's constrained prompt work.
- `skill_lecture_deck_building.md` gets a small addition documenting this (see §8) so it isn't
  only captured in this plan file.

## 7. Data flow summary (concrete file list, before vs. after)

| Artifact | v2 (current) | v3 (this plan) |
|---|---|---|
| `topic_content.json` | `{key_facts, mechanism, data_points, appendix}` per (reading, topic) | `{key_facts, mechanism, data_points}` only |
| `appendix.md` | Auto-generated by `run_lecture_prep.py`, every (reading, topic) pair with any content | Generated by `appendix_writer.py`, only for pairs explicitly requested by a built deck |
| `appendix_content.json` | (didn't exist) | NEW — per-request cache, keyed by (reading, topic, ask) |
| Outline markdown | Informal, produced ad hoc when discussing a deck | Formalized: must include `## Appendix Requests` block |

## 8. Skill file update needed

`skill_lecture_deck_building.md`'s existing "Appendix pointers" section gets one addition:
whenever an "Appendix:" note is written on a slide, also add the corresponding entry to the
outline markdown's `## Appendix Requests` block in the schema from §4.1 — the two should never
drift apart (every in-slide appendix pointer has a matching request entry, and vice versa).

## 9. Acceptance checklist, once built

- [ ] `topic_content.json` entries no longer contain an `appendix` key going forward
- [ ] `run_lecture_prep.py` no longer writes `appendix.md`
- [ ] `appendix_writer.py` runs entirely off cached `map_candidates.json` — verify via a run
      with network/API access disabled for the map phase specifically (only reduce-2 calls should
      fire)
- [ ] A request against a reading with no map cache (abstract-only) still produces a reasonable
      (if thinner) appendix section rather than failing
- [ ] Generated appendix sections contain none of the prohibited generic headers (Introduction /
      Background / Overview / Conclusion / Findings) — spot check against the CoDriVE and
      Kwajalein sections specifically, since those are the ones that showed the problem clearest
      in the v2 output
- [ ] Re-running `appendix_writer.py` unchanged is a no-op (full cache hit, no LLM calls)
- [ ] Changing one request's `ask` text regenerates only that request, not the whole file
- [ ] `appendix.md` groups by topic (framework sequence order) then reading, matching v2's
      grouping behavior
- [ ] `skill_lecture_deck_building.md` updated per §8
