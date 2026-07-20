# Meta-pipeline: Building an ICTD-style course

This document lists the steps we are following to build this course, and will
later be used as the basis for a set of reusable skills for building future
courses of this kind (new topic focus, new year, new instructor emphasis,
etc). Each numbered step below is a candidate for its own detailed skill file.

Note on ordering: the steps are numbered in the order they were originally
scoped, but execution order has since been revised -- see "Execution order"
at the bottom. Step 4 (course website) has been moved up to be tackled next,
ahead of Steps 5-6 (selection utility, class schedule), since a working
website gives the instructor a much better surface for reviewing the
framework/readings/examples data than raw JSON does.

## Step 1 — Framework
Define the course's `areas x topics` matrix (and any cross-cutting axes) and
encode it as `framework.json`. Areas are application domains for innovation;
topics are the research/engineering skill stages that generalize across
areas; cross-cutting axes (gender, caste, social capital, climate change,
etc.) modulate every cell rather than standing alone. Also includes an
area-agnostic topic vector: a pure-methodology description per topic plus
curated example readings that teach that topic's methodology independent of
any one area (e.g. Sen and Piketty for problem_discovery; Schumacher for
cs_fundamentals).
**Output:** `framework.json`
**Status:** Done

## Step 2 — Reading list curation
Search for and select good papers/book chapters/books/videos/other resources
that map into the framework, drawing on prior course iterations, dedicated
ICTD/COMPASS/FAccT/AIES/IJCAI-AISI/etc. venues (see `venues.json`), general
literature search, and instructor-supplied sources (including full books and
YouTube/TED videos, which turned out to need their own careful metadata
handling). Each reading gets tagged with area(s), topic(s), cross-cutting
axes, and an `area_agnostic` flag; venue/year/abstract metadata is populated
either via targeted search (for a small number of high-priority items) or a
local bulk-enrichment script (`enrich_metadata.py`) for the long tail, with
instructor spot-checks correcting errors along the way.
**Output:** `readings.json`
**Status:** Ongoing (currently 259 readings from 4 original courses + IJCAI
2025 + instructor-supplied books/videos; local scraping in progress for
Climate Change AI, IJCAI 2022-24, KDD, FAccT, GHTC, AAAI AISI, and a second
wave of venues added to `venue_configs.py` for COMPASS/ICTD/JCSS/CHI/CSCW/
AIES/ITID/IFIP ICT4D/Development Engineering). New readings will keep
arriving and feeding back into this step.

## Step 3 — Case study / example generation
Identify broad recurring domains within each area (e.g. voice-based
agricultural extension, REDD+ forest carbon offsets, Aadhaar-style biometric
digital identity) -- not single projects, but groupings of similar projects
and readings within an area, spanning multiple topics. Each case study
references the controlled vocabulary in `framework.json` (areas, topics,
cross-cutting axes) and a set of reading ids from `readings.json`; topic and
axis coverage per case study is derived automatically from its constituent
readings rather than hand-curated, so it can never drift out of sync.
**Output:** `examples.json`
**Status:** Done for the current readings.json snapshot (43 case studies
across all 11 areas, covering 214/259 readings -- the area-agnostic readings
are intentionally excluded here since they're handled by Step 1's
area-agnostic topic vector instead). Will need periodic re-generation /
extension as Step 2 keeps adding readings.

## Step 4 — Course website
Build a static website (HTML/CSS/JS, no backend) presenting the course:
a main page introducing the course's intellectual framing and the areas x
topics structure, an examples page rendering `examples.json` grouped by
area with per-topic reading columns (title, authors, year, venue, DOI link,
hover-to-see-abstract), and a placeholder link to a future class-schedule
page. Content-authored-in-Markdown, data-driven from the JSON files, so
updates to `readings.json`/`framework.json`/`examples.json` don't require
touching the site's code.
**Output:** static site (`index.html` + supporting pages/assets) + the
Markdown source for the main page's prose content + a build plan for
whoever implements it
**Status:** Main page content drafted this turn; implementation handed off
(see `website_build_plan.md`)

## Step 5 — Selection utility
Build a utility (script/notebook/small app) that helps the instructor filter
and select a subset of readings from `readings.json` for a given offering,
based on constraints like: number of classes, desired area/topic coverage,
reading load per class, mix of theory/case-study/technical papers, and
recency.
**Output:** selection tool + a chosen subset of readings for the offering
**Status:** Not started

## Step 6 — Class-by-class schedule
Using the selected readings, build the actual week-by-week / class-by-class
schedule: sequencing (e.g. problem_discovery classes early, impact_evaluation
and operations_scale classes later), grouping by area, slots for student
presentations, guest lectures, project milestones, etc. Feeds into the
website's third page (Step 4).
**Output:** `schedule.json` (or similar) + human-readable schedule + the
website's class-schedule page
**Status:** Not started

## Step 7 — Skills extraction
Once the above steps have been run end-to-end at least once, write reusable
skill files (SKILL.md-style) distilling each step above into a procedure that
can be reused for future courses (new domain focus, new semester, etc.),
including the schemas used, the search/curation heuristics, the
selection-utility logic, the scheduling heuristics, and the website
generation approach.
**Output:** a set of skill files under a `skills/` directory
**Status:** Not started — planned as the final step, informed by this chat
history

## Execution order
Steps are not being executed strictly in numeric order. Actual sequence:
1. Step 1 (framework) — done
2. Step 2 (readings) — done for current snapshot, ongoing as new venues are scraped
3. Step 3 (examples) — done for current snapshot
4. **Step 4 (website) — next**
5. Step 5 (selection utility) — after Step 4
6. Step 6 (class schedule) — after Step 5, feeds the website's third page
7. Step 7 (skills extraction) — last

## Working files in this project
- `framework.json` — areas x topics x cross-cutting-axes matrix, plus area-agnostic topic vector
- `readings.json` — reading list mapped onto the framework
- `venues.json` — venue-level index of conferences/journals/tracks for literature search
- `examples.json` — domain-level case studies per area, cross-referencing readings.json
- `local_pipeline/` — local scraping + LLM-filtering + metadata-enrichment scripts
- `meta_pipeline.md` — this file
- `website_build_plan.md` — implementation plan for Step 4 (this turn)
- `main_page_content.md` — Markdown source for the website's main page (this turn)

