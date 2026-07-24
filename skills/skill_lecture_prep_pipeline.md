---
name: ictd-lecture-prep-pipeline
description: >
  Given a case study id from examples.json, prepare slide-facts material for building a lecture
  deck: resolve/download PDFs, extract text and figures, optionally score book alignment, and
  run map-reduce topic content extraction. Produces lecture_prep_manifest.json for Claude to
  build slides from. Extended appendix notes are a separate on-demand step (appendix_writer.py)
  after the deck outline exists. Trigger when asked to prepare source material for a lecture.
---

# ICTD Lecture Prep Pipeline (v3)

## What this does and doesn't do

This skill prepares **source material**, not the slides themselves. It answers: *what can I
actually read and see from these papers, and what concrete facts exist per course topic* — the
slide narrative, pacing, and layout are a separate step (Claude + `skill_lecture_deck_building.md`,
once this pipeline's output is available).

It exists because a real problem shows up as soon as you try to build a lecture from a case
study's reading list: **most conference papers are paywalled**. An LLM can find a DOI and
abstract via search, but not the PDF without your institutional access. This pipeline
auto-downloads what's legitimately open and produces a clear checklist for what you must fetch
yourself — it is designed around that reality rather than pretending it away.

**v3 change:** extended appendix notes are **not** produced automatically. `run_lecture_prep.py`
writes slide-facts only. The full path to a finished deck alternates local scripts and Claude —
see [Full lecture workflow](#full-lecture-workflow-local--claude).

## When to use this vs. asking Claude directly

Use this pipeline when a case study includes readings behind institutional paywalls (ACM DL,
IEEE Xplore, Springer, ScienceDirect, etc.) — which is most non-trivial case studies. If every
reading is already open access (arXiv, preprints, OA journals), you can often skip straight to
Claude with abstracts/links, without running this locally.

Even with open access, run the pipeline when you want **per-topic slide facts** (`key_facts`,
`mechanism`, `data_points`), **figure extraction**, and a **consolidated manifest** rather than
ad-hoc abstract summaries.

## What this produces

### Automatic (`run_lecture_prep.py`)

| Artifact | Purpose |
|----------|---------|
| `access_manifest.json` | Per-reading access status, paths to extracted files |
| `pdfs/<reading_id>.pdf` | Auto- or manually-downloaded PDFs |
| `extracted/<reading_id>/text.txt` | Plain text (book alignment scorer input) |
| `extracted/<reading_id>/text.md` | Section-structured markdown (topic map phase input) |
| `extracted/<reading_id>/figures/` | Embedded images + caption guesses |
| `book_alignment.json` | Optional book/CoRE-Stack alignment scores |
| `map_candidates.json` | Map-phase cache — **keep this**; appendix writer reuses it |
| `topic_content.json` | Reduce-phase cache: slide facts per (reading, topic) |
| `lecture_prep_manifest.json` | **Handoff file** for deck building |

The manifest includes `topic_content` (key_facts, mechanism, data_points), optional
`alignment`, figures, and access status — sorted by alignment score when alignment ran.

### On demand (after deck + outline exist)

| Artifact | Purpose |
|----------|---------|
| `appendix_content.json` | Per-request cache, keyed by (reading, topic, ask) |
| `appendix.md` | Targeted extended notes, grouped by framework topic then reading |

See `skill_lecture_deck_building.md` for deck-building conventions and how the outline's
`## Appendix Requests` block is produced.

## Full lecture workflow (local ↔ Claude)

The complete path from case study to finished deck alternates between **local scripts** and
**Claude chat** (using `skill_lecture_deck_building.md`). Set `$OUT_DIR` / `$EXAMPLE_ID` as in
[End-to-end procedure](#end-to-end-procedure).

| Step | Where | Action |
|------|-------|--------|
| **1** | Local | Run `run_lecture_prep.py` → `lecture_prep_manifest.json` |
| **2** | Claude | Upload manifest (+ optional figure folders). Attach `skill_lecture_deck_building.md`. Ask for **`outline.md`** with slide table + `## Appendix Requests`. |
| **3** | Local | Save downloaded `outline.md` to `$OUT_DIR/outline.md`. Run `appendix_writer.py` → `appendix.md`. |
| **4** | Claude | Upload `appendix.md` (+ manifest/outline if new chat). Attach deck-building skill. Ask Claude to **generate the final `.pptx`**, pulling appendix detail into slides that requested it. |

**Step 2 — example prompt:**

> Build a lecture outline for this case study from the attached `lecture_prep_manifest.json`.
> Follow `skill_lecture_deck_building.md`. Deliver `outline.md` with a slide-by-slide table and
> a complete `## Appendix Requests` block for every in-slide appendix pointer.

**Step 3 — local command:**

```bash
python skills/appendix_writer.py \
  --out-dir $OUT_DIR \
  --outline $OUT_DIR/outline.md
```

Spot-check `appendix.md` for empty sections before step 4 (see deck-building skill, step-4 QA).

**Step 4 — example prompt:**

> Using the attached `appendix.md` and the earlier manifest/outline, build the final lecture
> `.pptx`. Follow `skill_lecture_deck_building.md`. Pull mechanisms, thresholds, and numbers
> from the appendix into slides that flagged them; cite `appendix.md` in speaker notes. Flag
> any appendix section that is missing or unreliable rather than inventing content.

Steps 2 and 4 may happen in one continuous chat (outline first, appendix uploaded later) or as
separate sessions — upload manifest + outline again if starting fresh for step 4.

## Pipeline shape (local scripts only)

```
resolve_and_download.py
        ↓
pdf_to_text_figures.py          → text.txt + text.md + figures
        ↓
book_alignment_scorer.py        (optional: --skip-alignment)
topic_content_extractor.py      → map_candidates.json + topic_content.json (slide facts only)
        ↓
run_lecture_prep.py               → lecture_prep_manifest.json
        ↓
[Claude: outline.md with ## Appendix Requests]     ← step 2
        ↓
appendix_writer.py                → appendix.md
        ↓
[Claude: final .pptx using appendix.md]            ← step 4
```

`book_alignment_scorer.py` and `topic_content_extractor.py` are independent siblings: both read
from the same extracted text; neither depends on the other's output. Either can be re-run alone
without invalidating the other's cache.

## Prerequisites

- **Python 3** with dependencies:
  `pip install requests pymupdf pymupdf4llm anthropic`
- **`.env`** at project root (see `.env.example`):
  - `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` — Claude API scripts
  - `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT` — local Ollama
  - `ALIGNMENT_BACKEND=ollama` or `anthropic` — book alignment scorer
  - `MAP_BACKEND` / `REDUCE_BACKEND` — topic content map/reduce phases (fall back to
    `ALIGNMENT_BACKEND` when unset)
- **`data/examples.json`**, **`data/readings.json`**, **`data/framework.json`**
- Book concept map defaults to the instructor's combined chapter summary
  (`00_COMBINED_All_Chapters_and_Concept_Map.md`; override with `--book-concept-map`)
- CoRE stack summary defaults to `CoRE_Stack_Computing_Elements.md` (override with
  `--core-stack-topic-map`)
- **Institutional library access** (proxy/VPN) for the manual-download step

## Output folder naming

Pass the **full original `--example-id`** on every command. Output goes under a shortened slug
folder, not the full id string:

```
data/lecture-prep/<truncated-example-id>_<hash>/
```

Example:

```
--example-id water_security_ai_flood_mapping_and_forecasting_from_satellite_data
→ data/lecture-prep/water_security_ai_flood_mapping_and_fore_ca464260290a/
```

The pipeline resolves the slug automatically (`pipeline_common.resolve_lecture_prep_out_dir`).
Registered paths are also tracked in `data/lecture-prep/index.json` after a first download run.

To discover the slug for any example id without running the full pipeline:

```bash
python -c "import sys; sys.path.insert(0,'skills'); from pipeline_common import lecture_prep_slug, resolve_lecture_prep_out_dir; eid='YOUR_EXAMPLE_ID'; print(lecture_prep_slug(eid)); print(resolve_lecture_prep_out_dir(eid))"
```

## End-to-end procedure

All commands assume the repo root as working directory. On Windows PowerShell, set variables
once and reuse them:

```powershell
Set-Location "path\to\ictd-course-creation"
$EXAMPLE_ID = "water_security_ai_flood_mapping_and_forecasting_from_satellite_data"
$OUT_DIR = "data/lecture-prep/water_security_ai_flood_mapping_and_fore_ca464260290a"
.\.venv\Scripts\Activate.ps1
```

On bash:

```bash
cd path/to/ictd-course-creation
EXAMPLE_ID="water_security_ai_flood_mapping_and_forecasting_from_satellite_data"
OUT_DIR="data/lecture-prep/water_security_ai_flood_mapping_and_fore_ca464260290a"
source .venv/bin/activate
```

### 1. First run — full slide-facts prep

One command chains download → extract → alignment (optional) → topic content → manifest:

```bash
python skills/run_lecture_prep.py --example-id $EXAMPLE_ID --skip-alignment
```

Omit `--skip-alignment` to run book/CoRE-Stack scoring (adds one LLM call per reading).

**If the script stops** because some non-video readings still lack PDFs:

1. Open `$OUT_DIR/manual_downloads_needed.md`
2. Save each file as `$OUT_DIR/pdfs/<reading_id>.pdf` (truncated browser filenames are matched
   by prefix — see `pipeline_common.find_pdf_for_reading`)
3. Re-run with `--skip-download`:

```bash
python skills/run_lecture_prep.py --example-id $EXAMPLE_ID --skip-download --skip-alignment
```

To continue with partial PDF coverage anyway:

```bash
python skills/run_lecture_prep.py --example-id $EXAMPLE_ID --skip-download --skip-alignment --force-processing
```

**Don't route around paywalls programmatically.** The manual-download checklist exists so a
human with legitimate access does that part.

### 2. Re-run topic content only

After PDFs are complete, or to refresh slide facts after prompt changes:

```bash
python skills/run_lecture_prep.py --example-id $EXAMPLE_ID --skip-download --skip-alignment --force-map --force-reduce
```

Map only or reduce only:

```bash
python skills/run_lecture_prep.py --example-id $EXAMPLE_ID --skip-download --skip-alignment --force-map
python skills/run_lecture_prep.py --example-id $EXAMPLE_ID --skip-download --skip-alignment --force-reduce
```

### 3. Individual steps (when debugging)

These are chained by `run_lecture_prep.py` but can be run alone:

```bash
python skills/resolve_and_download.py --example-id $EXAMPLE_ID --out-dir $OUT_DIR
python skills/pdf_to_text_figures.py --out-dir $OUT_DIR
python skills/book_alignment_scorer.py --out-dir $OUT_DIR
python skills/topic_content_extractor.py --out-dir $OUT_DIR
```

## Step details

### Resolve access and download (`resolve_and_download.py`)

Categorizes every reading as: auto-downloaded (open PDF), video/talk (no PDF — use
abstract/description), or needs-manual-download (paywalled — checklist with DOI and title).

The orchestrator **stops** when non-video readings lack PDFs unless you pass
`--force-processing`.

### Extract text and figures (`pdf_to_text_figures.py`)

Uses PyMuPDF for per-page plain text and embedded images. Also writes **`text.md`** via
`pymupdf4llm` — section headings drive the topic-content map phase.

Figure captions are a **heuristic first draft** (nearest "Figure N: ..." text on the same page,
position-blind). Verify by eye before putting a figure on a slide.

### Book alignment (`book_alignment_scorer.py`, optional)

For each reading (full text if available, abstract otherwise), produces alignment score (1–5),
connected themes, paraphrased notable findings, and a presentation framing note.

**Prompt routing:**

- **Book alignment** — readings that are neither `area_agnostic` nor tagged `cs_fundamentals`
- **CoRE stack alignment** — background-domain and `cs_fundamentals` readings, scored against
  `CoRE_Stack_Computing_Elements.md`

**Backend:** one LLM call per reading. Default from `ALIGNMENT_BACKEND` in `.env`, or
`--backend ollama|anthropic` via `run_lecture_prep.py`. Cached in `book_alignment.json`;
re-run with `--force-alignment` after concept-map edits.

Use alignment to **prioritize speaking time**, not to silently drop pedagogically necessary
readings. A low-scoring reading may still establish the technical baseline others react to.

Skip entirely with `--skip-alignment` when topic content is the primary signal.

### Topic content — map/reduce (`topic_content_extractor.py`)

**Scope:** one extraction per topic **actually tagged on that reading** in `readings.json` — a
reading with `[cs_fundamentals, sociotechnical_dynamics]` produces exactly two blocks, never all
six framework topics.

**Map phase** (topic-agnostic, one call per section chunk):

- Input: `text.md` sections from `get_section_chunks()`, or fixed-window fallback if no headings
  detected
- Output: flat candidate list per chunk → `map_candidates.json`
- Dedup near-duplicates across chunks before reduce
- Backend: `MAP_BACKEND` or `--map-backend` (Ollama is typical for bulk work)

**Reduce phase** (topic-aware, one call per reading × topic):

- Input: deduped candidates + topic description
- Output per pair: `key_facts`, `mechanism`, `data_points` only — **no appendix field (v3)**
- Backend: `REDUCE_BACKEND` or `--reduce-backend` (Anthropic is typical for synthesis quality)

**Caching:**

| Phase | Cache file | Force flag |
|-------|------------|------------|
| Map | `map_candidates.json` | `--force-map` |
| Reduce | `topic_content.json` | `--force-reduce` |

Adding a new topic to an already-mapped reading re-runs reduce only, not map.

**Call volume:** roughly 3–8 map calls per reading plus one reduce call per (reading, topic).
A 13-reading case study is meaningfully more expensive than alignment alone (9 calls). Run
lecture-prep **per case study, on demand** — don't batch every example preemptively.

**Risks on first run:**

- Heading detection in `text.md` can fail silently on two-column or unusual layouts — spot-check
  `extracted/<reading_id>/text.md` on 2–3 dense papers before trusting the whole corpus
- Map/reduce with Ollama may return JSON with unescaped newlines; the pipeline repairs this in
  `src/ollama_client.py` — if a section comes back empty, re-run with `--force-reduce` and
  check for WARNING lines

### Consolidate manifest (`run_lecture_prep.py`)

Merges access status, topic content, optional alignment, and inlined figures into
`lecture_prep_manifest.json`. This completes **workflow step 1** — next handoff is to Claude
(see [Full lecture workflow](#full-lecture-workflow-local--claude)).

### Claude handoffs (workflow steps 2 and 4)

**Step 2 — outline from manifest:** Upload `$OUT_DIR/lecture_prep_manifest.json`. Optionally
upload `$OUT_DIR/extracted/<reading_id>/figures/` for readings where you want figures pulled
into slides. Attach `skills/skill_lecture_deck_building.md`. Ask for `outline.md` (slide table +
`## Appendix Requests`). Download the outline and save it as `$OUT_DIR/outline.md`.

Appendix request schema:

```markdown
## Appendix Requests
- reading: <reading_id>
  topic: <topic_id>
  ask: "<specific, narrow question — not 'more about this paper'>"
```

Worked example: `skills/reference/outline.md`. Every in-slide "Appendix:" pointer must have a
matching entry; vague `ask` strings produce paper-shaped appendix sections.

**Step 4 — presentation from appendix:** After local appendix generation (below), upload
`$OUT_DIR/appendix.md` back to Claude with the deck-building skill. Ask for the final `.pptx`.
See step-4 QA notes in `skill_lecture_deck_building.md` (empty appendix sections, confabulated
thresholds, shipping partial decks).

### Generate appendix locally (workflow step 3)

```bash
python skills/appendix_writer.py \
  --out-dir $OUT_DIR \
  --outline $OUT_DIR/outline.md
```

Uses cached `map_candidates.json` only — no PDF re-extraction. Backend: `REDUCE_BACKEND` or
`--backend ollama|anthropic`.

Regenerate after changing an `ask` string:

```bash
python skills/appendix_writer.py --out-dir $OUT_DIR --outline $OUT_DIR/outline.md --force
```

Re-running unchanged is a no-op (full cache hit). Changing one `ask` regenerates only that
request.

**Appendix heading hierarchy** (for table-of-contents tools):

| Level | Role |
|-------|------|
| `#` | Document title |
| `##` | Framework topic |
| `###` | Reading title |
| `####` | Section within a reading (How it works, Thresholds, …) |
| `#####` | Nested sub-points under a section |

`appendix_writer.py` normalizes LLM output to this hierarchy automatically.

Appendix sections are organized around **mechanism → criteria/thresholds → concrete
examples**, not paper-shaped Introduction/Methods/Findings/Conclusion headers.

## CLI reference (`run_lecture_prep.py`)

| Flag | Purpose |
|------|---------|
| `--example-id` | Full case study id from `examples.json` (required) |
| `--out-dir` | Override output directory (default: slug under `data/lecture-prep/`) |
| `--skip-download` | Resume from existing manifest/PDFs |
| `--force-processing` | Continue when some PDFs are still missing |
| `--skip-alignment` | Skip `book_alignment_scorer.py` |
| `--backend` | Alignment scorer backend |
| `--force-alignment` | Re-score all readings |
| `--map-backend` / `--reduce-backend` | Topic content backends |
| `--force-map` / `--force-reduce` | Re-run cached topic content phases |

## CLI reference (`appendix_writer.py`)

| Flag | Purpose |
|------|---------|
| `--out-dir` | Lecture-prep folder with `map_candidates.json` |
| `--outline` | Deck outline containing `## Appendix Requests` |
| `--backend` | LLM backend (default: `REDUCE_BACKEND`) |
| `--force` | Bypass `appendix_content.json` cache |

## Common mistakes

- **Don't expect `run_lecture_prep.py` to produce `appendix.md`** — v3 moved that to
  `appendix_writer.py`, driven by the deck outline.
- **Don't skip manual PDFs and build only from abstracts** for your highest-priority readings —
  abstracts lack figures and nuance needed to paraphrase accurately.
- **Don't trust figure captions blindly** — verify before using in a slide.
- **Don't let alignment score be the only filter** — use it to allocate speaking time, not to
  drop pedagogically necessary readings silently.
- **Don't write vague appendix `ask` strings** — specificity drives quality.
- **Re-run `--force-reduce`** if you changed slide-facts prompts; **`--force`** on
  `appendix_writer.py` if you changed an `ask` text.
- **Re-run alignment** if you edit the book concept-map or CoRE stack summary.
- **Keep `map_candidates.json`** between runs — deleting it forces an expensive re-map and breaks
  appendix generation until map completes again.

## v2 → v3 migration notes

| Artifact | v2 | v3 |
|----------|----|----|
| `topic_content.json` | included `appendix` field | `key_facts`, `mechanism`, `data_points` only |
| `appendix.md` | auto-generated for every (reading, topic) with content | on demand via `appendix_writer.py` |
| `appendix_content.json` | did not exist | per-request cache |

Stale `appendix` keys in old `topic_content.json` caches are harmless; `--force-reduce` cleans
them up on regeneration.

## Related files

- `skills/skill_lecture_deck_building.md` — deck content, appendix pointers, outline conventions
- `skills/reference/outline.md` — worked outline + appendix requests example
- `skills/reference/pipeline_v3_appendix_plan.md` — design rationale for v3 appendix split
- `skills/reference/revised_lecture_pipeline_plan.md` — design rationale for v2 topic content
