---
name: ictd-lecture-deck-building
description: >
  Build a PowerPoint lecture deck from a lecture_prep_manifest.json (produced by the
  resolve/extract/align/topic-content pipeline) for an ICTD-style case study. Use this whenever
  asked to turn a case study's extracted readings into a course lecture presentation. Encodes
  content-selection, synthesis, figure-handling, and sourcing conventions established across
  several actual lecture-building sessions -- read this before building another deck, not just
  the first time.
---

# ICTD Lecture Deck Building

## What kind of deck this produces

An **informative lecture on the case study's domain** -- e.g. "how does climate vulnerability
assessment actually work, what tools exist, did they work" -- not a lecture about how the
readings relate to any one theoretical framework (the instructor's book, CoRE Stack, etc.).
Framework/book alignment scores are a **prioritization signal**, not the narrative spine. If a
manifest includes `book_alignment` / `alignment` data, use it to decide which readings earn a
full slide versus a supporting mention -- don't build slides that explain "how this reading
relates to the book" unless explicitly asked to.

## End-to-end workflow (v3)

The full process runs in **four handoffs**, alternating between local execution (instructor's
machine, API/Ollama) and chat-based work (Claude, using this skill):

1. **Instructor generates the slide-facts manifest locally** — `run_lecture_prep.py` (resolve →
   extract → align → topic content) produces `lecture_prep_manifest.json`. No appendix content
   at this stage. See `skill_lecture_prep_pipeline.md` for commands.
2. **Claude builds the deck outline from the manifest** — instructor uploads
   `lecture_prep_manifest.json` (and optionally `extracted/<reading_id>/figures/` folders),
   attaches this skill, and asks Claude to produce **`outline.md`**: slide-by-slide table plus
   a `## Appendix Requests` block for whatever needs more depth than a slide can hold. A draft
   `.pptx` may be produced here, but the outline is the required handoff artifact for the next
   local step.
3. **Instructor generates the appendix locally** — save `outline.md` into the lecture-prep
   folder, then run `appendix_writer.py`. This reuses cached map-phase candidates (no PDF
   re-extraction) and writes targeted `appendix.md` sections for exactly those requests.
4. **Claude builds or sharpens the final presentation** — instructor uploads `appendix.md`
   (and the earlier manifest/outline if starting a fresh chat), attaches this skill, and asks
   Claude to generate the `.pptx`. Pull specific mechanisms, thresholds, and numbers from the
   appendix into slides that requested them; update speaker notes to cite `appendix.md` as the
   source.

**QA discipline for step 4** (learned from prior runs — don't trust the appendix blindly just
because it exists):

- **Check every requested section actually has content.** A known failure mode is a request
  producing a header with zero content underneath — silent generation failure, not something
  diff-style skimming catches easily. Grep for headers followed by only blank lines before
  trusting an appendix file is complete.
- **Watch for near-identical definitions given to differently named things** — e.g. two
  distinct technical indices described with the same underlying formula is a strong signal of
  model confabulation, not a genuine coincidence. When this happens, don't put the specific
  numeric claim on a slide; either omit it, hedge it explicitly ("the paper isn't fully
  consistent on this exact threshold"), or flag it in speaker notes as needing verification
  against the source PDF directly.
- **When an appendix section is missing or unreliable, still ship the rest of the deck** —
  don't block six good sections on one bad one. Flag the specific gap in speaker notes (which
  request, why it's unusable) so it's visible and actionable, not silently worked around.

## Content selection

- **Synthesize by topic, then by domain-narrative -- never build the deck reading-by-reading.**
  A deck that walks through each of 9 readings in turn, one slide per reading, produces a list,
  not a lecture. Group by the six course topics (problem_discovery through operations_scale),
  and within a topic, look for the throughline across multiple readings before writing any slide
  content.
- **When several readings share a topic, cap it at ~2 full slides, fold the rest in as brief
  supplementary content.** A topic with 4-5 tagged readings does not get 4-5 slides -- pick the
  two most substantive/complementary (not necessarily the two highest-scoring on any alignment
  metric alone; complementary in what they teach matters more than raw score) for full
  treatment, and give the remaining readings a single shared "in brief" slide, or fold their
  distinct facts into other slides as one-line supporting mentions. Don't let this cap become a
  hard rule that produces redundant slides either -- if two readings on the same topic say
  materially the same thing, only one needs the full slide regardless of how many total readings
  exist for that topic.
- **Actively cross-reference between topics rather than treating them as silos.** If the same
  institutional mechanism (e.g. a specific governance body, a specific tool) shows up in a
  reading's `problem_discovery` content and again in its `ethnographic_design` content, say so
  explicitly on the later slide ("as introduced on Slide N...") rather than re-explaining it from
  scratch or, worse, ignoring the connection. A synthesis slide that makes an implicit connection
  explicit (e.g. "these two 'assessment' readings are actually participatory design in
  disguise") is worth including even when it isn't sourced from any single reading's extracted
  content -- but **must be flagged as editorial synthesis in the speaker notes**, not presented
  as a direct finding.
- **A thin topic (1 reading, or weak content) still gets a real slide if the topic itself
  matters pedagogically** (e.g. socio-technical dynamics / power questions) -- don't skip it for
  lack of source material. Build it honestly from what exists, and use editorial synthesis
  grounded in facts already established elsewhere in the deck to fill it out, clearly flagged as
  such in speaker notes rather than presented as a single paper's finding.
- **Name data/evidence gaps in the source material as content, not as something to hide.** If
  one reading in the case study is still `needs_manual_download` with no extracted content, say
  so on whichever slide it would have belonged to, with the reading's id, so the instructor can
  decide whether to fetch it before delivering. If a reading is explicitly self-described as
  preliminary ("initial observations"), keep that framing rather than overstating its findings
  as settled.

## Figures

- **Never require figures to be uploaded before building the deck.** Mark a "suggested figure"
  callout directly on the slide: the source reading, page number, and the (possibly imperfect)
  extracted caption text, styled neutrally (not as an error state -- these are deferred choices,
  not failures). The instructor adds the actual image later.
- **State plainly when a reading's caption-extraction has known problems** (e.g. a previous
  pipeline run found a captioned figure that turned out to be a decorative icon, not the real
  diagram) so the instructor knows to double-check before trusting a caption blindly, without
  re-litigating the whole verification process in the deck itself.
- **When a reading has an unusually rich, well-captioned figure set, say so** -- it signals to
  the instructor that this is worth extra time picking the single best image rather than
  defaulting to the first plausible caption.
- If images *are* supplied in a future round: verify every one by actually looking at it before
  using it (file size alone is a decent tripwire -- a suspiciously small file, e.g. under a few
  KB, is very likely a decorative icon, not the intended diagram) and reframe the slide's content
  around what the image actually shows if it doesn't match its extracted caption, rather than
  forcing a caption that doesn't fit the real content.

## Appendix pointers

Mark a slide with an explicit "Appendix:" pointer whenever the slide references a
process/method/framework in enough depth that a student would plausibly want the fuller version
(a multi-step method, a technical index's computation, a framework's full structure) -- point to
what the appendix would need to cover, even if the appendix document itself isn't in hand yet
when the deck is built.

**Every in-slide "Appendix:" pointer must also get a matching entry in the outline markdown's
`## Appendix Requests` block** (v3 pipeline change -- appendix generation is now a separate,
on-demand step run *after* the outline exists, driven by exactly these requests, not an automatic
pass over every reading). The two should never drift apart. Format:

```markdown
## Appendix Requests
- reading: <reading_id>
  topic: <topic_id>
  ask: "<specific, narrow question -- not 'more about this paper'>"
```

The `ask` text should be the same specific, narrow phrasing already used in-slide (e.g. *"full
5-step method detail, including how the Vulnerability Code is computed"*, not *"more about
CoDriVE"*) -- specificity here is what keeps the generated appendix section focused on a
mechanism instead of drifting into a paper-shaped summary. A generic or vague `ask` will produce
a generic or vague appendix section; write it as precisely as the actual pedagogical need.

See `skills/reference/outline.md` for a worked example.

## Sourcing and traceability

- Every slide's speaker notes should name which reading id(s) and manifest field(s)
  (`key_facts`/`mechanism`/`data_points`, or explicitly "editorial synthesis") the slide's
  content came from. This is what makes it possible to audit a slide's claims later without
  re-deriving them from scratch.
- Flag explicitly in speaker notes when a reading's overall alignment classification (e.g.
  scored against a technical/computing reference rather than a social/institutional one) means
  it shouldn't be used for a framing it wasn't suited to on a given slide.
- Discussion prompts should reference specific facts/slides established earlier in the deck, not
  be generic prompts that could apply to any lecture on any topic.

## Build process (mechanical, from prior sessions)

1. Read the skill(s) at `/mnt/skills/public/pptx/SKILL.md` before writing any code.
2. Build with `pptxgenjs`, `LAYOUT_WIDE`, a consistent small palette (a dark anchor color for
   section dividers/emphasis panels, one accent color, a light neutral for content panels) reused
   across every deck for this course rather than reinvented per lecture.
3. After building: run `validate.py`, then a content-QA text grep for placeholder patterns
   (accept that generic word-matching greps will throw false positives -- e.g. "NaN" matching
   inside "financial" -- verify hits by eye before treating them as real problems), then convert
   to images and visually inspect every slide for overflow/overlap before delivering. If image
   rendering is unavailable in a given session, fall back to validate.py + content grep + file-size
   sanity checks, and say so plainly rather than silently skipping visual QA.
4. Deliver the `.pptx` plus an **outline markdown** (topic-by-topic slide list with figure
   requests and the `## Appendix Requests` block) in the same response -- don't make the
   instructor open the file to find out what's in it before deciding whether to review further.
