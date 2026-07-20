# Local venue-ingestion pipeline

Runs the same three-step process we used for the IJCAI pilot (scrape → keyword prefilter →
LLM relevance+tagging → dedup against readings.json), but locally, so it can chew through
Climate Change AI / KDD / FAccT / GHTC / AAAI without burning conversation turns.

## Setup

```bash
pip install requests beautifulsoup4 lxml
# only needed for GHTC (IEEE Xplore) and possibly Climate Change AI if no embedded JSON is found:
pip install playwright && playwright install chromium

# Ollama, if not already running:
ollama pull qwen2.5
ollama serve   # usually starts automatically after pull/install
```

Copy this whole `local_pipeline/` folder so it sits *next to* your `framework.json` and
`readings.json` (or adjust the paths passed to `process_venue()` in `run_pipeline.py`).

## Run

```bash
# one venue at a time (recommended -- review each before moving on):
python src/run_pipeline.py climate_change_ai
python src/run_pipeline.py ijcai_2024
python src/run_pipeline.py kdd_2025
# ...etc, keys are in venue_configs.py

# or the whole remaining queue in the order you specified:
python src/run_pipeline.py all
```

Each run produces two files per venue:

- `candidates_<venue>.json` — papers the LLM marked relevant, with suggested area/topic/axis
tags and its one-sentence reasoning in `notes`. **Review this by hand.**
- `skipped_<venue>.json` — everything filtered out, tagged with *why* (duplicate / no keyword
overlap / LLM said irrelevant + its reason). Worth a skim to catch false negatives, especially
early on while you're calibrating trust in qwen2.5's judgment.



## Review & merge

Open `candidates_<venue>.json`, delete entries you disagree with, optionally fix the `id` field
(a short slug), then:

```bash
python src/merge_candidates.py data/candidates_kdd_2025.json data/readings.json
```

This re-checks for duplicates against the *live* readings.json (including anything merged from
other venues since the candidates file was generated) before appending.

## Tuning notes

- **Selectors will likely need adjustment.** I could not verify raw HTML against these live
sites in the conversation that produced this code (my fetch tool returns cleaned text, not
HTML source) — the CSS selectors in `scrapers.py` are my best knowledge of each platform's
typical markup, marked `# ADJUST ME`. Inspect one real page per venue type and fix as needed.
- **ACM DL bot detection**: if `scrape_acm_dl_proceedings()` gets blocked, save the page as HTML
from your browser (Ctrl+S) and use `scrape_acm_dl_proceedings_from_file()` instead.
- **qwen2.5 model size**: the default `qwen2.5` (7B) should be fine for this classification task,
but if you notice bad JSON output or weak judgment calls, try `qwen2.5:14b` and change `MODEL`
in `ollama_filter.py`.
- **min_hits in keyword_prefilter()**: currently 1 (any single keyword hit passes to the LLM).
Raise to 2-3 if too much junk is reaching the LLM step and slowing things down; lower recall
risk if you do.
- **The prompt in** `ollama_filter.py` **is a first draft** — after reviewing a batch of
`candidates_*.json` / `skipped_*.json`, you'll likely want to tighten or loosen the
developing-regions rule wording based on what you see qwen2.5 getting wrong.

