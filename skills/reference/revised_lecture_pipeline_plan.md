# Lecture-Prep Pipeline v2: Topic-Content Extraction + Standalone Appendix

Implementation plan only — no code yet, per instruction. Covers exactly what changes, in which
files, and why, so this can be reviewed and signed off before anything is written.

## 1. What this adds, in one sentence

A new pipeline stage that mines each reading for concrete, topic-organized content (not
book/CoRE-Stack relevance) via map-reduce chunked extraction, producing both slide-ready
material and a longer standalone appendix document — while leaving the existing
download → extract → align stages and their resumability/caching conventions untouched.

## 2. Pipeline shape after this change

```
resolve_and_download.py   (unchanged)
        |
pdf_to_text_figures.py    (+ text.md via pymupdf4llm, alongside existing text.txt)
        |
        +---> book_alignment_scorer.py      (unchanged — book/CoRE-Stack relevance, demoted role)
        |
        +---> topic_content_extractor.py    (NEW — map-reduce topic content, this plan's focus)
        |
run_lecture_prep.py       (orchestrates all of the above, assembles two handoff artifacts:
                            lecture_prep_manifest.json AND appendix.md)
```

`book_alignment_scorer.py` and `topic_content_extractor.py` are independent siblings, both
consuming the same `access_manifest.json`/`text.md`, neither depending on the other's output.
Either can be re-run alone without touching the other's cache.

## 3. New file: `skills/topic_content_extractor.py`

### 3.1 Per-reading, per-topic scope
For each reading, run the extraction once per topic **actually in that reading's own
`topics` list** from `readings.json` — a reading tagged `[cs_fundamentals, sociotechnical_dynamics]`
produces exactly two topic-content blocks, never all six.

### 3.2 Map phase (topic-agnostic, chunked, per section)
- Input: `text.md` sections (see §5) or fixed-window fallback chunks.
- One call per chunk. Prompt is deliberately **topic-agnostic and dumb-and-narrow**, matching
  the lesson from the case-study generator: "extract concrete facts, mechanisms, numbers, and
  anything methodologically interesting from this section — don't sort them into topics yet."
- Output per chunk: a flat list of candidate items, each tagged with a rough type
  (`fact` / `mechanism` / `data_point` / `nugget`) and a `location_hint` (the real section name
  from `text.md`, not a guess — this is the concrete quality win from switching extractors).
- **Dedup candidates across chunks before reduce**: reuse the existing fuzzy word-overlap
  matcher already established as a codebase convention (same approach as domain-name merging in
  `generate_examples_via_api.py` and the reading-dedup logic elsewhere) to collapse near-duplicate
  candidates — a fact restated across overlapping chunk windows shouldn't reach reduce twice.
- **Backend**: `--map-backend {anthropic,ollama}`. This is the phase meant to absorb bulk,
  cheap, parallelizable work — the natural place to point at local Ollama qwen2.5:14b.

### 3.3 Reduce phase (topic-aware, one call per reading × topic)
- Input: the deduped candidate list from 3.2, filtered to what's relevant to *this* topic,
  plus the reading's title/authors/topic-description for context.
- One call produces, for that (reading, topic) pair:
  ```json
  {
    "key_facts": ["...", "..."],
    "mechanism": "40-60 word slide-ready summary of how the process/system works",
    "data_points": ["...", "..."],
    "appendix": "150-1500 words, organized with ## subheadings and bullet points as needed —
                  a briefing-note-length writeup of this reading's contribution to this topic.
                  Liberal quoting allowed here (longer than the 15-word slide-safe limit used
                  elsewhere) since this is a course-internal document, not slide text."
  }
  ```
- `appendix` length is a target range, not a fixed count — a reading with a lot to say about a
  topic gets closer to 1500 words with real subsections; a reading that's thin on a topic
  produces less rather than being padded to hit a floor. The prompt should say this explicitly
  ("write as much as the source material actually supports, organized clearly — don't pad").
- **Backend**: `--reduce-backend {anthropic,ollama}`, independent of `--map-backend`. Expected
  common pattern: `--map-backend ollama --reduce-backend anthropic` (cheap bulk extraction
  locally, better synthesis quality on the smaller reduce input).

### 3.4 Caching / resumability
Follow the exact pattern already established in `book_alignment_scorer.py`
(`is_cache_hit`/`load_alignment_cache`/`save_alignment_cache`), applied at **two granularities**:
- Map-phase cache key: `(reading_id, chunk_index, map_backend, map_model)` — stored per reading
  so adding a new topic to an already-mapped reading doesn't re-run extraction, only reduce.
- Reduce-phase cache key: `(reading_id, topic, reduce_backend, reduce_model)` — stored in
  `topic_content.json`, mirroring `book_alignment.json`'s shape and location.
- `--force-map` / `--force-reduce` flags, separate from each other (mirrors `--force` on the
  existing scorer, split because map is the expensive phase and you may want to force a reduce
  re-run — e.g. after tweaking the reduce prompt — without paying for re-mapping).

## 4. Changed file: `skills/pdf_to_text_figures.py`

- Add `pymupdf4llm` as a dependency; call `pymupdf4llm.to_markdown(pdf_path)` alongside the
  existing `fitz`-based plain-text extraction — **keep both outputs**, don't replace `text.txt`.
  `text.md` is the primary input for chunking; `text.txt` remains the fallback (and keeps
  `book_alignment_scorer.py` working unchanged, since it reads `text_path`).
- Write `text.md` next to `text.txt` in the same `extracted/<reading_id>/` directory.
- `access_manifest.json` entries gain a `text_md_path` field alongside the existing `text_path`,
  same naming convention as the rest of the manifest.
- Figure extraction logic (JPX handling, caption-guess heuristic) is untouched.

## 5. Changed file: `skills/pipeline_common.py`

One new shared helper, in the same style as `find_pdf_for_reading`:

```python
def get_section_chunks(text_md_path, fallback_window_pages=3):
    """
    Split a pymupdf4llm markdown file on heading markers (^#{1,3}\\s) into
    (section_name, section_text) pairs. If zero headings are detected (heading-detection
    failure on an unconventionally-styled paper), fall back to fixed windows of
    ~fallback_window_pages worth of text with slight overlap, named "Pages N-M".
    """
```

Lives here (not inside `topic_content_extractor.py`) because it's a general "get me sensible
chunks of a paper" utility — plausibly useful to `book_alignment_scorer.py` too in a future pass
(better `location_hint` grounding there as well), even though this plan doesn't wire that up yet.

## 6. Changed file: `skills/run_lecture_prep.py`

- New step in the orchestration sequence: `topic_content_extractor.py`, with its own
  `--map-backend`/`--reduce-backend`/`--force-map`/`--force-reduce` flags threaded through from
  `run_lecture_prep.py`'s own CLI (mirroring how `--backend`/`--force-alignment` are already
  threaded through to `book_alignment_scorer.py`).
- Final consolidation gains a **second output artifact**, alongside the existing
  `lecture_prep_manifest.json`:
  - `lecture_prep_manifest.json` — unchanged shape plus each reading entry gains
    `topic_content: {topic_id: {key_facts, mechanism, data_points}}` (the `appendix` field is
    deliberately **excluded** from this file — it's slide-prep material, the appendix field
    would just bloat the handoff manifest with content that belongs in its own document).
  - `appendix.md` — **NEW**, assembled by topic (not by reading), matching how the lecture
    itself is organized:
    ```
    # <Case Study Name> — Extended Notes

    ## Problem Discovery
    ### <Reading 1 title>
    <that reading's problem_discovery appendix content>
    ### <Reading 2 title>
    ...

    ## Computing Elements
    ### <Reading title>
    ...
    ```
    Only topics with at least one reading contributing appendix content get a heading (same
    "don't pad empty sections" principle as everything else in this pipeline).
- Closing message updated to mention both output files, not just the manifest.

## 7. Unchanged files

- `resolve_and_download.py` — no changes; this stage's job (get a PDF onto disk, or flag for
  manual download) is unaffected by anything in this plan.
- `book_alignment_scorer.py` — no changes to its logic. Its role in the final lecture is
  **demoted per your clarification**: still runs, still cached, but its output
  (`book_alignment`) is folded into the handoff manifest as a secondary/optional callout rather
  than the primary content, which is now `topic_content`. (This is a presentation-layer
  decision for whoever builds slides from the manifest, not a code change to the scorer itself.)

## 8. Estimated call volume (this one case study, 9 readings, ~2.5 topics/reading average)

- Map phase: roughly 3-8 chunks per reading depending on paper length → ~40-70 calls total,
  all on whichever backend `--map-backend` names (cheap if Ollama).
- Reduce phase: ~22-25 calls (one per reading × topic), on `--reduce-backend`.
- Compare to the existing `book_alignment_scorer.py` run: 9 calls. This stage is meaningfully
  more expensive in call count, which is the direct tradeoff for depth — worth confirming
  you're comfortable with that before a full run, especially if `--reduce-backend anthropic`.

## 9. Open risks worth watching on the first real run, not blocking, but flagged honestly

- **Heading-detection reliability is unverified on your actual corpus.** `pymupdf4llm`'s
  heading heuristic (font size/boldness) can fail silently on two-column layouts or unusual
  templates — the fixed-window fallback covers total failure (zero headings found), but a
  *partial* misdetection (e.g. only 2 of 6 real sections recognized) will produce lopsided,
  not-obviously-wrong chunks. Worth spot-checking `text.md` output on 2-3 of your denser PDFs
  (CRISP-M, the ICTD 2024 water-security paper) before trusting it across the whole corpus.
- **Reduce-phase appendix length is a soft target, not a guarantee.** Some (reading, topic)
  pairs will legitimately produce well under 150 words if the map phase surfaced little — that's
  correct behavior per your "don't pad" instruction, but means `appendix.md` will read unevenly
  across sections. Worth deciding later whether that's fine (honest reflection of source depth)
  or whether thin sections should be flagged/merged rather than left short.
- **Cost/time scaling**: this plan's call volume (§8) is for one 9-reading case study. Given
  you're also running the case-study generator at 1000+ readings scale elsewhere in this
  project, worth being deliberate about running lecture-prep per-case-study, on demand, rather
  than batch-processing every case study's readings preemptively.

## 10. Acceptance checklist, once built

- [ ] `text.md` written for every successfully-extracted PDF, `text.txt` still also present
- [ ] A reading tagged with N topics produces exactly N `topic_content` blocks, never more/fewer
- [ ] Map-phase cache survives adding a new topic to an already-processed reading (no re-map)
- [ ] `--force-reduce` alone re-runs reduce without re-running map
- [ ] `appendix.md` groups by topic first, reading second, and omits empty topic sections
- [ ] `lecture_prep_manifest.json` does NOT contain the long-form `appendix` text
- [ ] A reading with zero detected headings still produces usable (fixed-window) chunks, not a
      failure
- [ ] `--map-backend ollama --reduce-backend anthropic` (the expected common case) runs
      end-to-end without requiring both env configs to be simultaneously "primary"
