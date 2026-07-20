# Website build plan (for Cursor)

## Goal

A static site (plain HTML/CSS/JS, no build step, no backend, no framework) with three pages:

1. **`index.html`** — main page. Renders `main_page_content.md` (provided) as the page body,
   plus a generated summary block listing all areas/topics/axes pulled live from
   `framework.json` (so it never drifts out of sync with the data file).
2. **`examples.html`** — renders `examples.json`, grouped by area, each case study showing its
   readings laid out in topic columns, pulling reading details from `readings.json`.
3. **`schedule.html`** — placeholder only for now ("Class schedule — coming soon", with a link
   back to the main page). A future turn will fill this in once `schedule.json` exists; don't
   build anything data-driven here yet, just the shell page so the nav link resolves.

All three pages share a header/nav (`Home | Examples | Class Schedule`) and one CSS file.

## Why static + client-side data loading

The instructor will keep regenerating `framework.json` / `readings.json` / `examples.json` as the
reading list grows (this has already happened many times). The site must **never require a
rebuild step** when those files change — it should `fetch()` them at page-load time and render
from them directly. Treat these three JSON files, plus `main_page_content.md`, as the site's only
content sources; don't hardcode any area/topic/reading data into the HTML/JS.

## File structure to create

```
site/
├── index.html
├── examples.html
├── schedule.html
├── css/
│   └── style.css
├── js/
│   ├── markdown-render.js      # loads + renders main_page_content.md on index.html
│   ├── framework-summary.js    # renders the areas/topics/axes list on index.html from framework.json
│   ├── examples-render.js      # renders examples.html from examples.json + readings.json + framework.json
│   └── shared.js               # shared helpers (fetch-json, DOI-link helper, author formatting, etc.)
├── data/
│   ├── framework.json          # copy of the instructor's file (or symlink — see "Data sync" below)
│   ├── readings.json
│   └── examples.json
└── content/
    └── main_page_content.md
```

Use a `data/` folder so the JS just does `fetch('data/framework.json')` etc. Copy the actual
JSON/MD files the instructor provides into `data/` and `content/` — don't regenerate or transform
them.

## Data contracts — read these carefully, field names must match exactly

### `framework.json`
Top-level keys: `course`, `areas`, `cross_cutting_axes`, `topics`, `matrix_usage_notes`,
`area_agnostic_topic_vector`, `area_agnostic_topic_vector_note`.

- `areas`: list of `{id, name, description, keywords}`. Iterate in list order (already
  meaningful order, don't re-sort alphabetically).
- `topics`: list of `{id, name, sequence, description, keywords}`. **Sort by `sequence`** (1-6)
  when displaying — this is the pedagogical order (problem_discovery → ... → operations_scale).
- `cross_cutting_axes`: list of `{id, name, description, keywords}`.

### `readings.json`
Top-level keys: `readings_list_metadata`, `readings`.

Each reading in `readings`:
```
{
  "id": string,                      // unique, use as a stable DOM id / anchor
  "title": string,
  "authors": string | null,          // free text, e.g. "Smith, J.; Doe, A." or "Smith, J. et al."
  "year": number | null,
  "areas": [string],                 // area ids, may be empty []
  "topics": [string],                // topic ids, at least one unless area_agnostic
  "cross_cutting_axes": [string],    // axis ids, may be empty []
  "source_course": string | [string],// not needed for display
  "notes": string | null,            // MAY contain "This is a book. " prefix, or sensitive-topic warnings
  "link": string | null,             // URL — hyperlink target. MAY BE NULL, handle gracefully (no link, just plain text title)
  "abstract": string | null,         // MAY BE NULL/MISSING — many readings don't have one yet
  "area_agnostic": boolean,
  "venue": string | null,            // MAY BE MISSING on many entries — handle gracefully
  "doi": string | null               // present on SOME entries only, from the enrichment script — prefer this over "link" as the hyperlink target when both exist and doi looks like a DOI
}
```

**Important data-quality realities to design for, not edge-case around later:**
- Not every reading has `abstract`, `venue`, or `year`. Missing = show nothing for that field,
  don't show "undefined" or "null".
- `authors` is free text of varying format — don't try to parse/reformat it structurally, just
  truncate visually if very long (see "Author formatting" below).
- `link` is sometimes a publisher page, sometimes a DOI URL, sometimes null. If `doi` field is
  present, prefer building the link from that (`https://doi.org/{doi}` if it's a bare DOI, or use
  it directly if it's already a full URL); otherwise fall back to `link`; otherwise the title is
  plain (non-clickable) text.
- Some readings' `notes` field starts with `"This is a book. "` — if so, render a small "book"
  badge/tag next to the title (see styling). Some notes mention sensitive topics (e.g. suicide
  risk) — if `notes` contains the substring `"SENSITIVE"` (case-insensitive), render a small
  content-warning badge.
- A reading whose `topics` array includes more than one of the case study's `topics_covered`
  appears in **one topic column only**, chosen by this precedence (highest wins):
  impact_evaluation → operations_scale → sociotechnical_dynamics → ethnographic_design →
  cs_fundamentals → problem_discovery. Do not duplicate the same reading across columns.

### `examples.json`
Top-level keys: `metadata`, `case_studies`.

Each entry in `case_studies`:
```
{
  "id": string,
  "name": string,
  "areas": [string],           // area ids; FIRST entry is the primary area — group the case
                                // study under this area's section on the page. Optionally also
                                // note "spans: X, Y" if there are secondary areas.
  "description": string,
  "topics_covered": [string],  // topic ids present, already in framework sequence order
  "cross_cutting_axes": [string],
  "readings": [string]         // reading ids — look these up in readings.json for display
}
```

## Page specs

### `index.html`
1. Header/nav (shared across all pages).
2. Render `content/main_page_content.md` as HTML in the main content area. Use a lightweight
   client-side Markdown renderer loaded from CDN — **use `marked.js`**
   (`https://cdn.jsdelivr.net/npm/marked/marked.min.js`), it's small, dependency-free, and needs
   no build step: `document.getElementById('main-content').innerHTML = marked.parse(mdText)`
   after fetching the `.md` file as text.
3. Below (or interleaved into, if it reads better — use your judgment) the rendered Markdown,
   render a live summary block from `framework.json`:
   - A numbered list of the 6 topics (sorted by `sequence`), each with its `name` and
     `description`.
   - A list/grid of area names (from `areas[].name`), each linking (`<a href="examples.html#area-{id}">`)
     to that area's section on the examples page.
   - A list of the 4 cross-cutting axis names.
   This block should be generated by JS from the JSON, not hand-written in the Markdown file,
   since the Markdown file's own "areas: Agriculture · Health · ..." line is prose for reading
   flow — the generated block is the canonical, always-in-sync version. Feel free to de-duplicate
   visually (e.g. only show the generated version, use the Markdown's prose line as a lead-in
   sentence) rather than showing the same list twice — use your judgment on the cleanest layout.

### `examples.html`
1. Header/nav.
2. Table of contents at the top: one link per area (in `framework.json` `areas` order) jumping to
   an anchor `#area-{area_id}` further down the page. Skip areas that have zero case studies.
3. For each area (in framework order):
   - Section heading with the area's `name`, anchored `id="area-{area_id}"`.
   - For each case study whose primary area (first entry in `areas`) matches this area:
     - Case study `name` as a sub-heading.
     - `description` as a paragraph.
     - If `areas` has more than one entry, a small note: "Also spans: {other area names}".
     - **Topic columns**: a horizontal set of columns (CSS grid or flexbox — responsive, wrap to
       fewer columns on narrow screens), one per topic in `topics_covered` **in framework
       sequence order** (skip columns with no readings). Column header = topic's `name` (from
       `framework.json`). Assign each reading to exactly one column: among the intersection of
       the reading's `topics` and the case study's `topics_covered`, pick the topic with highest
       precedence — impact_evaluation > operations_scale > sociotechnical_dynamics >
       ethnographic_design > cs_fundamentals > problem_discovery.
     - Each reading rendered as a compact card:
       - Title, hyperlinked per the link/doi logic above (if no URL available, plain bold text,
         not a link).
       - "book" badge if applicable (see data contract notes above).
       - Authors (see "Author formatting" below), year, venue on one line, e.g.
         *Smith, J. et al. — 2021 — ACM COMPASS*. Omit any of these three that are missing,
         and omit the whole line if all three are missing.
       - **On hover** (or `:focus` for keyboard accessibility — don't make it hover-only), show
         the abstract. Implement as a CSS-only tooltip (`title` attribute is NOT sufficient — it's
         slow to appear and unstyled; build a small custom tooltip: absolutely-positioned `<div>`
         toggled via `:hover`/`:focus-within` and a CSS transition). If no `abstract` field, don't
         attach a tooltip at all (no empty tooltip on hover).
       - If the case study's `cross_cutting_axes` includes axes relevant to *this specific
         reading* (i.e. intersect with the reading's own `cross_cutting_axes`), show small colored
         tag chips (e.g. "gender", "caste") on the card. Use a distinct color per axis, consistent
         across the whole site (define once in CSS variables).

### `schedule.html`
Just the shared header/nav plus a centered message: "Class schedule — coming soon." and a link
back to `index.html`. Nothing else. Don't fetch any JSON on this page yet.

## Author formatting
`authors` is a free-text string, semicolon-or-comma-separated in practice (format isn't fully
consistent across entries, so don't try to be clever). Display rule: if the string is longer than
~60 characters, truncate to roughly the first name/segment and append "et al." — e.g.
`"Dell'Acqua, Fabrizio; McFowland, Edward III; Mollick, Ethan; ..."` → `"Dell'Acqua, Fabrizio et al."`.
Implement as a simple string-split-on-`;`-or-`,`-then-take-first-segment heuristic; this doesn't
need to be perfect, just reasonable.

## Styling notes
- Clean academic-reading-list feel: generous whitespace, serif or readable sans-serif for body
  text, monospace not needed anywhere.
- Topic columns on the examples page should be visually distinct (e.g. subtle vertical rules or
  background-tint alternation) so it's clear at a glance which column a reading sits in.
- Make sure the tooltip (abstract on hover) doesn't get clipped by column overflow — use
  `overflow: visible` on ancestors or position the tooltip via JS if CSS positioning proves
  fragile near viewport edges.
- Mobile: topic columns should stack vertically below some breakpoint (~768px) rather than
  horizontally scroll — this is a reading list, not a spreadsheet.
- Keep it to one shared `css/style.css` — no per-page stylesheets, no CSS framework needed (this
  is simple enough for hand-written CSS; don't pull in Bootstrap/Tailwind for this).

## Serving locally (note this in a README you add to `site/`)
Because the pages `fetch()` local JSON/Markdown files, opening `index.html` directly via
`file://` will fail in most browsers due to CORS restrictions on local file fetches. Document
this and provide the fix: run a trivial local server from the `site/` directory, e.g.
`python3 -m http.server 8000`, then visit `http://localhost:8000/index.html`. Add this as a
one-line note in a `site/README.md`.

## Data sync note
For now, just copy `framework.json`, `readings.json`, `examples.json`, and
`main_page_content.md` into `site/data/` and `site/content/` as static files. The instructor will
manually re-copy updated versions in as they regenerate them upstream — don't build any
auto-sync/watch tooling for this yet, that's out of scope for this pass.

## Acceptance checklist
- [ ] `index.html` renders the Markdown content correctly (headings, links, bold, lists all work)
- [ ] All Knight Columbia / ICML talk / act.html / arXiv / DOI links in the main page open correctly
- [ ] The generated topics/areas/axes summary on `index.html` matches `framework.json` exactly
      (spot check: 6 topics in sequence order, 11 areas, 4 axes)
- [ ] `examples.html` shows a working table of contents jumping to each area section
- [ ] Every case study's topic columns are in framework `sequence` order, not alphabetical or
      JSON-array order
- [ ] A reading with 2+ topics appears in exactly one column, using topic precedence
      (impact_evaluation > operations_scale > sociotechnical_dynamics > ethnographic_design >
      cs_fundamentals > problem_discovery)
- [ ] A reading with no `link`/`doi` renders as plain (non-clickable) title text, no broken `href="null"`
- [ ] A reading with no `abstract` has no tooltip/hover affordance at all
- [ ] A reading with no `venue`/`year` doesn't show stray punctuation (e.g. no dangling "—" with
      nothing after it)
- [ ] Book-flagged readings show the book badge; the one sensitive-topic reading shows its warning
- [ ] Site works when served via `python3 -m http.server` and fails gracefully (clear console
      error, not a blank page) if opened via `file://`
- [ ] Mobile viewport (~375px wide) stacks topic columns vertically and remains readable
- [ ] `schedule.html` exists, is linked from the nav on all pages, and doesn't error on load
