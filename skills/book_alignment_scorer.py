"""
Step 3 of the lecture-prep pipeline: for each reading (extracted text, or abstract for videos),
identify how it connects to the instructor's book's arguments OR to the CoRE stack computing
elements topic summary, and draft notable passages worth building a slide around.

Install: pip install anthropic requests

Usage:
    python skills/book_alignment_scorer.py --out-dir data/lecture-prep/<example-id>
    python skills/book_alignment_scorer.py --out-dir data/lecture-prep/<example-id> --backend ollama

Defaults: data/readings.json, book concept map, CoRE stack topic summary (pipeline_common.py).
Backend: anthropic (default) or ollama -- see .env (ANTHROPIC_* / OLLAMA_* / ALIGNMENT_BACKEND).

Writes:
    <out-dir>/book_alignment.json   -- per-reading alignment (resumable; re-scores when text
                                        source changes or --force is set)

Scoring prompt selection:
    - Book alignment prompt: readings that are neither background-domain nor cs_fundamentals
    - CoRE stack topic alignment prompt: background-domain (area_agnostic) and cs_fundamentals
"""
import os
import re
import json
import argparse

import anthropic

from pipeline_common import (
    DEFAULT_READINGS,
    DEFAULT_BOOK_CONCEPT_MAP,
    DEFAULT_CORE_STACK_TOPIC_MAP,
    require_anthropic_key,
    uses_core_stack_alignment,
    get_anthropic_model,
    get_ollama_model,
    get_alignment_backend,
)
from src.ollama_client import ollama_generate, extract_json_object

BOOK_ALIGNMENT_PROMPT = """You are helping an instructor prepare a lecture on the case study "{cs_name}"
that draws heavily on their own book. Here is a summary of the book's key arguments and
vocabulary (from its concept map):

{book_summary}

Here is the text (or, if no PDF was available, the abstract) of one reading in this case study:
---
TITLE: {title}
AUTHORS: {authors}
TEXT:
{text}
---

Identify how this reading connects to the book's arguments. Respond with ONLY a JSON object:
{{
  "alignment_score": <1-5, how directly this reading's findings support/illustrate/complicate the book's arguments>,
  "matched_book_themes": ["short theme name", "..."],
  "notable_passages": [
    {{"paraphrase": "one sentence paraphrasing a specific finding or claim relevant to the book (NOT a verbatim quote)",
      "location_hint": "e.g. 'abstract', 'section 4', 'conclusion' -- best guess from the text",
      "short_quote": "OPTIONAL: a genuinely short (<15 words) verbatim phrase if one is unusually quotable, else omit this key"}}
  ],
  "presentation_note": "1-2 sentences: how would you frame this specific reading when presenting it alongside the book's argument -- does it support, extend, or complicate the book's claims?"
}}
"""

CORE_STACK_ALIGNMENT_PROMPT = """You are helping an instructor prepare a lecture on the case study "{cs_name}".
This reading is tagged as computing-elements or background-domain material. Score it against the
CoRE stack computing-elements reference below (data structures, geospatial pipelines, ML/AI
methods, and infrastructure patterns used in CoRE Stack), not against the instructor's broader
social/institutional book arguments.

CoRE stack computing-elements summary:
{core_stack_summary}

Here is the text (or, if no PDF was available, the abstract) of one reading in this case study:
---
TITLE: {title}
AUTHORS: {authors}
TEXT:
{text}
---

Identify how this reading connects to the CoRE stack's technical vocabulary, methods, or design
patterns. Respond with ONLY a JSON object:
{{
  "alignment_score": <1-5, how directly this reading's methods/findings map onto CoRE stack computing elements>,
  "matched_core_stack_themes": ["short theme name", "..."],
  "notable_passages": [
    {{"paraphrase": "one sentence paraphrasing a specific technical finding or method relevant to CoRE stack (NOT a verbatim quote)",
      "location_hint": "e.g. 'abstract', 'methods', 'section 4' -- best guess from the text",
      "short_quote": "OPTIONAL: a genuinely short (<15 words) verbatim phrase if one is unusually quotable, else omit this key"}}
  ],
  "presentation_note": "1-2 sentences: how would you frame this reading when teaching the computing-elements arc of the lecture -- does it exemplify, extend, or complicate CoRE stack patterns?"
}}
"""


def load_summary_markdown(path, max_chars=6000):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return content[:max_chars]


def get_reading_text(entry, readings_by_id, max_chars=12000):
    r = readings_by_id.get(entry["id"], {})
    if entry.get("text_path") and os.path.exists(entry["text_path"]):
        with open(entry["text_path"], encoding="utf-8") as f:
            text = f.read()
        return text[:max_chars], "full_text"
    abstract = r.get("abstract")
    if abstract:
        return abstract, "abstract_only"
    return None, "no_text_available"


def build_prompt(cs_name, book_summary, core_stack_summary, entry, readings_by_id):
    r = readings_by_id.get(entry["id"], {})
    text, source = get_reading_text(entry, readings_by_id)
    if text is None:
        return None, source, None, None

    use_core_stack = uses_core_stack_alignment(r)
    if use_core_stack:
        prompt = CORE_STACK_ALIGNMENT_PROMPT.format(
            cs_name=cs_name,
            core_stack_summary=core_stack_summary,
            title=r.get("title", entry["id"]),
            authors=r.get("authors", "?"),
            text=text,
        )
        alignment_type = "core_stack"
    else:
        prompt = BOOK_ALIGNMENT_PROMPT.format(
            cs_name=cs_name,
            book_summary=book_summary,
            title=r.get("title", entry["id"]),
            authors=r.get("authors", "?"),
            text=text,
        )
        alignment_type = "book"
    return prompt, source, alignment_type, text


def call_llm(prompt, backend, anthropic_client, model_name):
    if backend == "ollama":
        return ollama_generate(prompt, model=model_name)
    response = anthropic_client.messages.create(
        model=model_name, max_tokens=1500, messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def parse_alignment_response(raw, alignment_type, source, backend, model_name):
    parsed = extract_json_object(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {
                "alignment_type": alignment_type,
                "source_used": source,
                "backend": backend,
                "model": model_name,
                "note": "Model response unparseable.",
            }
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {
                "alignment_type": alignment_type,
                "source_used": source,
                "backend": backend,
                "model": model_name,
                "note": "Model response invalid JSON.",
                "_raw": raw,
            }
    parsed["alignment_type"] = alignment_type
    parsed["source_used"] = source
    parsed["backend"] = backend
    parsed["model"] = model_name
    return parsed


def is_cache_hit(cached, source, backend, model_name, force):
    if force:
        return False
    if not cached or not cached.get("alignment_score"):
        return False
    if cached.get("source_used") != source:
        return False
    if cached.get("backend") != backend:
        return False
    if cached.get("model") != model_name:
        return False
    return True


def load_alignment_cache(out_dir):
    path = os.path.join(out_dir, "book_alignment.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_alignment_cache(out_dir, alignment):
    path = os.path.join(out_dir, "book_alignment.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(alignment, f, indent=2)


def score_reading(cs_name, book_summary, core_stack_summary, entry, readings_by_id,
                  backend, anthropic_client, model_name):
    built = build_prompt(cs_name, book_summary, core_stack_summary, entry, readings_by_id)
    prompt, source, alignment_type, _text = built
    if prompt is None:
        return {"source_used": source, "note": "No text or abstract available -- skipped."}

    raw = call_llm(prompt, backend, anthropic_client, model_name)
    return parse_alignment_response(raw, alignment_type, source, backend, model_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--book-concept-map", default=str(DEFAULT_BOOK_CONCEPT_MAP))
    parser.add_argument("--core-stack-topic-map", default=str(DEFAULT_CORE_STACK_TOPIC_MAP))
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument(
        "--backend",
        choices=("anthropic", "ollama"),
        default=None,
        help="LLM backend (default: ALIGNMENT_BACKEND from .env, else anthropic)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-score all readings even if cached in book_alignment.json",
    )
    args = parser.parse_args()

    backend = (args.backend or get_alignment_backend()).lower()
    if backend not in ("anthropic", "ollama"):
        raise SystemExit(f"Unknown backend '{backend}'. Use anthropic or ollama.")

    anthropic_client = None
    if backend == "anthropic":
        require_anthropic_key()
        anthropic_client = anthropic.Anthropic()
        model_name = get_anthropic_model()
    else:
        model_name = get_ollama_model()

    book_summary = load_summary_markdown(args.book_concept_map)
    core_stack_summary = load_summary_markdown(args.core_stack_topic_map)

    manifest_path = os.path.join(args.out_dir, "access_manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    with open(args.readings, encoding="utf-8") as f:
        readings_by_id = {r["id"]: r for r in json.load(f)["readings"]}

    cs_name = manifest.get("case_study_id", "this case study")
    alignment = load_alignment_cache(args.out_dir)
    cached_hits = 0

    print(f"Backend: {backend}  model: {model_name}")

    for entry in manifest["readings"]:
        reading = readings_by_id.get(entry["id"], {})
        prompt_kind = "core_stack" if uses_core_stack_alignment(reading) else "book"
        built = build_prompt(cs_name, book_summary, core_stack_summary, entry, readings_by_id)
        _prompt, source, _alignment_type, _text = built

        cached = alignment.get(entry["id"], {})
        if is_cache_hit(cached, source, backend, model_name, args.force):
            print(f"  cached ({prompt_kind}): {entry['id']}")
            cached_hits += 1
            entry["book_alignment_score"] = cached.get("alignment_score")
            entry["alignment_type"] = cached.get("alignment_type")
            continue

        print(f"Scoring ({prompt_kind}): {entry['id']}")
        result = score_reading(
            cs_name, book_summary, core_stack_summary, entry, readings_by_id,
            backend, anthropic_client, model_name,
        )
        alignment[entry["id"]] = result
        entry["book_alignment_score"] = result.get("alignment_score")
        entry["alignment_type"] = result.get("alignment_type")
        save_alignment_cache(args.out_dir, alignment)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    scored = [e for e in alignment.values() if e.get("alignment_score")]
    print(f"\nDone. {len(scored)} readings scored ({cached_hits} from cache).")
    print("Ranked by alignment (highest first) -- consider prioritizing these for lecture time:")
    for rid, e in sorted(alignment.items(), key=lambda kv: kv[1].get("alignment_score", 0), reverse=True):
        if e.get("alignment_score"):
            kind = e.get("alignment_type", "?")
            print(f"  {e['alignment_score']}/5  [{kind}]  {rid}")


if __name__ == "__main__":
    main()
