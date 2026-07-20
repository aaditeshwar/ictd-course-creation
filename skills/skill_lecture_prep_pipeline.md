---
name: ictd-lecture-prep-pipeline
description: >
  Given a case study id from examples.json, prepare everything needed to build a lecture deck
  about it: resolve and download each reading's PDF where legitimately possible, flag the rest
  for manual (institutional-access) download, extract text and figures from whatever PDFs are
  available, and score each reading's alignment with the instructor's own book so the lecture
  can prioritize the readings that best support the book's arguments. Produces one consolidated
  manifest file meant to be handed back into a chat with Claude to actually build the slides.
  Trigger this skill when asked to prepare source material for a lecture/presentation built
  around one of the case studies in examples.json.
---

# ICTD Lecture Prep Pipeline

## What this does and doesn't do

This skill prepares **source material**, not the slides themselves. It answers "what can I
actually read/see from these papers, and which ones matter most for the argument I want to
make" -- the actual slide narrative and layout is a separate step (done by Claude in a chat,
using a `.pptx`-building tool, once this pipeline's output is available).

It exists because a real, unglamorous problem shows up as soon as you try to build a lecture
from a case study's reading list: **most conference papers are paywalled**, and an LLM assistant
without your institutional library access can find a DOI and an abstract via search, but not the
actual PDF. This pipeline is designed around that reality rather than pretending it away -- it
auto-downloads what's legitimately open, and produces a clear checklist for what you'll need to
fetch yourself.

## When to use this vs. just asking Claude directly

Use this pipeline when a case study includes readings behind institutional paywalls (ACM DL,
JSTOR, AEA, Springer, ScienceDirect, IEEE Xplore are the common ones in an ICTD reading list) --
which is most non-trivial case studies. If every reading in the case study is already open
access (arXiv, preprint servers, open-access journals), you can often skip straight to asking
Claude to work from the abstracts/links directly, without running this locally at all.

## Prerequisites

- Python 3 with `requests`, `pymupdf`, and `anthropic` installed
  (`pip install requests pymupdf anthropic`)
- `.env` at the project root (see `.env.example`):
  - `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` for Claude API scripts
  - `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT` for local Ollama
  - `ALIGNMENT_BACKEND=ollama` or `anthropic` for step 3 scoring
- `data/examples.json` and `data/readings.json` (defaults; case study and readings must exist)
- Book concept map defaults to the instructor's combined chapter summary at
  `.../00_COMBINED_All_Chapters_and_Concept_Map.md` (override with `--book-concept-map` if needed)
- CoRE stack computing-elements summary defaults to
  `.../CoRE_Stack_Computing_Elements.md` (override with `--core-stack-topic-map` if needed)
- Your own institutional access (library proxy login, VPN, etc.) for the manual-download step

## Procedure

### 1. Resolve access and auto-download what's legitimately open

Run `python skills/resolve_and_download.py --example-id <id>` (or use `run_lecture_prep.py`
which chains all steps). This categorizes every reading in the case
study into: auto-downloaded (open PDF, e.g. arXiv/IJCAI preprints), video/talk (no PDF to
extract -- use its abstract/description text instead), or needs-manual-download (paywalled --
writes a checklist with DOI and title so you can fetch it through your library access).

If any non-video readings still lack a PDF, the orchestrator **stops** and waits for you to
drop files into `data/lecture-prep/<slug>/pdfs/<reading_id>.pdf`, then **re-run the same
command** (it picks up PDFs already on disk). Use `--force-processing` to continue with
partial coverage anyway.

New case studies use a shortened folder name under `data/lecture-prep/`:
`<truncated-example-id>_<hash>/` (e.g.
`data/lecture-prep/water_security_climate_resilience_tools_19b1fe3d0340/`). Pass the **full
original `--example-id`** on the command line; the pipeline resolves the slug folder
automatically.

**Don't try to route around paywalls programmatically.** Scraping around institutional access
controls is both against most publishers' terms and a bad foundation for a course that, per the
instructor's own book, argues technologists should be accountable actors, not just clever ones.
The manual-download checklist exists precisely so a human with legitimate access does that part.

### 2. Extract text and figures from whatever PDFs are now present

Run `python skills/pdf_to_text_figures.py --out-dir data/lecture-prep/<slug>/` (after dropping any manually-downloaded PDFs into
`pdfs/<reading_id>.pdf` following the checklist from step 1). Uses PyMuPDF to pull per-page text
and every embedded image, with a **heuristic, position-blind caption guess** per figure (nearest
"Figure N: ..." text found on the same page) -- treat captions as a first draft to verify by eye
when picking which figure actually goes on a slide, not as ground truth.

### 3. Score each reading against the instructor's book or CoRE stack computing elements

Run `python skills/book_alignment_scorer.py --out-dir data/lecture-prep/<id>/`. For each reading (full
extracted text if a PDF was available, abstract otherwise), asks the model for: an alignment
score (1-5), which specific themes it connects to, a few *paraphrased* notable findings (not
verbatim block quotes -- these are copyrighted academic papers; keep any direct quote under ~15
words, matching ordinary fair-use/copyright-conscious practice), and a presentation framing note.

**Prompt routing:**
- **Book alignment prompt** -- readings that are neither background-domain (`area_agnostic`) nor
  tagged `cs_fundamentals`
- **CoRE stack topic alignment prompt** -- background-domain and `cs_fundamentals` readings, scored
  against `CoRE_Stack_Computing_Elements.md` (override path with `--core-stack-topic-map`)

**Backend:** one LLM call per reading (not two). Choose `anthropic` (default unless
`ALIGNMENT_BACKEND=ollama` in `.env`) or `--backend ollama` for local Qwen via Ollama.
Results are cached in `book_alignment.json` and skipped on re-run unless the text source changes
(abstract → full PDF text) or you pass `--force` / `--force-alignment` via `run_lecture_prep.py`.

This step is what turns "9 readings, no idea where to spend your 40 minutes" into a ranked list
-- readings that scored low can be cut or mentioned briefly; readings that scored high are where
the lecture's actual argumentative weight should go.

### 4. Consolidate and hand off

`python skills/run_lecture_prep.py --example-id <id>` chains steps 1-3 and writes one
`data/lecture-prep/<id>/lecture_prep_manifest.json` per case study containing: the case study's
own metadata (name, description, topics, background_concepts if present), and every reading with
its access status, extracted text path, figures (inlined), and book-alignment result, sorted by
alignment score descending.

Hand this file (and the `figures/` folders, if you want actual images pulled into slides) back
into a chat with Claude and ask for the deck. Don't try to have this pipeline generate the
`.pptx` itself -- slide narrative, pacing, and layout benefit from being done conversationally
with a model that can adjust to feedback turn by turn, not from a one-shot script.

## Common mistakes to avoid

- **Don't skip the manual-download checklist and just build the lecture from abstracts.**
  Abstracts don't give you figures or the nuance needed to accurately paraphrase a finding --
  worth the friction of actually fetching the PDFs for the highest-alignment-score readings at
  minimum, even if you skip it for low-scoring ones.
- **Don't trust figure captions blindly.** The caption-matching heuristic is position-blind
  (nearest caption-like text on the page, not spatially nearest to the image) -- a paper with
  several figures on one page can mismatch. Eyeball before using in a slide.
- **Don't let the book-alignment score be the only filter.** A reading can score low on
  book-alignment but still be pedagogically necessary (e.g. it's the paper that establishes the
  technical baseline the higher-scoring readings react to). Use the ranking to prioritize
  *speaking time*, not to silently drop readings from the lecture's reading list.
- **Re-run book_alignment_scorer.py if you edit the book concept-map or CoRE stack topic summary**
  -- the scoring is only as good as the theme summaries it's given; a thin or stale summary
  produces thin alignment reasoning.
