"""
Orchestrates the full lecture-prep pipeline for one case study (example_id), then writes the
consolidated slide-facts handoff manifest:

    lecture_prep_manifest.json  -- slide-prep material: per-reading topic_content
                                    (key_facts/mechanism/data_points), book/CoRE-Stack alignment
                                    as a secondary callout, figures, access status. Hand this to
                                    Claude in a chat to build the PowerPoint from.

NOTE (v3 change): this script no longer produces appendix.md. Extended/appendix notes are now
generated on demand, AFTER a deck exists, by appendix_writer.py -- driven by the specific
"## Appendix Requests" the deck-building process flags, not run automatically for every
(reading, topic) pair here. See appendix_writer.py's docstring for why.

Usage:
    python skills/run_lecture_prep.py --example-id gov_egovernance_accountability

Defaults: data/examples.json, data/readings.json, data/framework.json, instructor book concept
map, CoRE stack topic summary, output under data/lecture-prep/<example-id>/.

Pipeline order: resolve_and_download.py -> (stop if PDFs missing, see manual_downloads_needed.md)
-> pdf_to_text_figures.py -> book_alignment_scorer.py + topic_content_extractor.py (independent
siblings, neither depends on the other's output) -> consolidate the slide-facts manifest.

Re-run the same command after dropping PDFs into pdfs/<reading_id>.pdf; the download step picks
up files already on disk. Use --force-processing to continue with partial PDF coverage anyway.
"""
import os
import sys
import json
import argparse
import subprocess

from pipeline_common import (
    DEFAULT_READINGS,
    DEFAULT_EXAMPLES,
    DEFAULT_FRAMEWORK,
    DEFAULT_BOOK_CONCEPT_MAP,
    DEFAULT_CORE_STACK_TOPIC_MAP,
    resolve_lecture_prep_out_dir,
    ensure_lecture_prep_dirs,
    readings_missing_pdf,
    refresh_manifest_pdf_status,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {' '.join(cmd)}")


def load_manifest(out_dir):
    manifest_path = os.path.join(out_dir, "access_manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(out_dir, manifest):
    manifest_path = os.path.join(out_dir, "access_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def ensure_pdfs_ready(out_dir, force_processing):
    manifest = load_manifest(out_dir)
    refresh_manifest_pdf_status(manifest, out_dir)
    save_manifest(out_dir, manifest)

    missing = readings_missing_pdf(manifest, out_dir)
    if missing and not force_processing:
        print(f"\n{len(missing)} readings still need a PDF before processing continues.")
        print(f"See {out_dir}/manual_downloads_needed.md")
        print("Drop each file at pdfs/<reading_id>.pdf, then re-run this script.")
        print("Use --force-processing to continue with partial PDF coverage anyway.")
        raise SystemExit(0)
    if missing and force_processing:
        print(f"\n--force-processing: continuing with {len(missing)} readings still missing PDFs.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--example-id", required=True)
    parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument("--framework", default=str(DEFAULT_FRAMEWORK))
    parser.add_argument("--book-concept-map", default=str(DEFAULT_BOOK_CONCEPT_MAP))
    parser.add_argument("--core-stack-topic-map", default=str(DEFAULT_CORE_STACK_TOPIC_MAP))
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--skip-download", action="store_true",
                        help="skip resolve_and_download.py (use existing access_manifest.json "
                             "and pdfs/; still checks PDF readiness unless --force-processing)")
    parser.add_argument("--force-processing", action="store_true",
                        help="continue even when some non-video readings still lack PDFs")
    parser.add_argument(
        "--backend",
        choices=("anthropic", "ollama"),
        default=None,
        help="book/CoRE-Stack alignment scorer backend (default: ALIGNMENT_BACKEND from .env)",
    )
    parser.add_argument(
        "--force-alignment",
        action="store_true",
        help="re-score all readings even if book_alignment.json cache exists",
    )
    parser.add_argument("--map-backend", choices=("anthropic", "ollama"), default=None,
                        help="topic-content map-phase backend (default: MAP_BACKEND env, "
                             "else ALIGNMENT_BACKEND)")
    parser.add_argument("--reduce-backend", choices=("anthropic", "ollama"), default=None,
                        help="topic-content reduce-phase backend (default: REDUCE_BACKEND env, "
                             "else ALIGNMENT_BACKEND)")
    parser.add_argument("--force-map", action="store_true",
                        help="re-run topic-content map phase even if cached")
    parser.add_argument("--force-reduce", action="store_true",
                        help="re-run topic-content reduce phase even if cached")
    parser.add_argument("--skip-alignment", action="store_true",
                        help="skip book_alignment_scorer.py entirely (topic_content is the "
                             "primary artifact now -- alignment is optional context)")
    args = parser.parse_args()

    out_dir = str(resolve_lecture_prep_out_dir(args.example_id, args.out_dir))
    pdf_dir = ensure_lecture_prep_dirs(out_dir)
    print(f"Lecture prep dir: {out_dir}")
    print(f"PDF folder: {pdf_dir}")

    if not args.skip_download:
        run([sys.executable, os.path.join(HERE, "resolve_and_download.py"),
             "--example-id", args.example_id, "--examples", args.examples,
             "--readings", args.readings, "--out-dir", out_dir])
    elif not os.path.exists(os.path.join(out_dir, "access_manifest.json")):
        raise SystemExit(
            f"No access_manifest.json under {out_dir}. Run without --skip-download first."
        )
    else:
        manifest = load_manifest(out_dir)
        refresh_manifest_pdf_status(manifest, out_dir)
        save_manifest(out_dir, manifest)
        print(f"Resuming from existing manifest in {out_dir}")

    ensure_pdfs_ready(out_dir, args.force_processing)

    run([sys.executable, os.path.join(HERE, "pdf_to_text_figures.py"), "--out-dir", out_dir])

    # ---- book/CoRE-Stack alignment: still runs, still cached, now a secondary/optional callout ----
    if not args.skip_alignment:
        scorer_cmd = [
            sys.executable, os.path.join(HERE, "book_alignment_scorer.py"),
            "--out-dir", out_dir,
            "--book-concept-map", args.book_concept_map,
            "--core-stack-topic-map", args.core_stack_topic_map,
            "--readings", args.readings,
        ]
        if args.backend:
            scorer_cmd.extend(["--backend", args.backend])
        if args.force_alignment:
            scorer_cmd.append("--force")
        run(scorer_cmd)
    else:
        print("\n--skip-alignment: skipping book_alignment_scorer.py")

    # ---- topic content: the primary artifact now ----
    topic_cmd = [
        sys.executable, os.path.join(HERE, "topic_content_extractor.py"),
        "--out-dir", out_dir, "--readings", args.readings, "--framework", args.framework,
    ]
    if args.map_backend:
        topic_cmd.extend(["--map-backend", args.map_backend])
    if args.reduce_backend:
        topic_cmd.extend(["--reduce-backend", args.reduce_backend])
    if args.force_map:
        topic_cmd.append("--force-map")
    if args.force_reduce:
        topic_cmd.append("--force-reduce")
    run(topic_cmd)

    # ================= consolidate into the two handoff artifacts =================
    with open(args.examples, encoding="utf-8") as f:
        examples = json.load(f)
    cs = next(c for c in examples["case_studies"] if c["id"] == args.example_id)

    manifest = load_manifest(out_dir)

    alignment = {}
    alignment_path = os.path.join(out_dir, "book_alignment.json")
    if os.path.isfile(alignment_path):
        with open(alignment_path, encoding="utf-8") as f:
            alignment = json.load(f)

    topic_content = {}
    topic_content_path = os.path.join(out_dir, "topic_content.json")
    if os.path.isfile(topic_content_path):
        with open(topic_content_path, encoding="utf-8") as f:
            topic_content = json.load(f)

    for entry in manifest["readings"]:
        reading_id = entry["id"]
        # slide-ready material only -- key_facts/mechanism/data_points. Longer-form appendix
        # content is generated separately, on demand, by appendix_writer.py (v3) -- not produced
        # or included here at all.
        entry["topic_content"] = {}
        for topic_id in entry.get("topics_extracted", []):
            tc = topic_content.get(f"{reading_id}::{topic_id}", {})
            entry["topic_content"][topic_id] = {
                "key_facts": tc.get("key_facts", []),
                "mechanism": tc.get("mechanism", ""),
                "data_points": tc.get("data_points", []),
            }
        # book/CoRE-Stack alignment folded in as secondary/optional context, not primary content
        entry["alignment"] = alignment.get(reading_id, {})
        if entry.get("figures_path") and os.path.exists(entry["figures_path"]):
            with open(entry["figures_path"], encoding="utf-8") as f:
                entry["figures"] = json.load(f)

    handoff = {
        "case_study": cs,
        "readings": sorted(
            manifest["readings"],
            key=lambda e: e.get("alignment", {}).get("alignment_score") or 0,
            reverse=True,
        ),
    }
    handoff_path = os.path.join(out_dir, "lecture_prep_manifest.json")
    with open(handoff_path, "w", encoding="utf-8") as f:
        json.dump(handoff, f, indent=2)

    print(f"\n{'='*70}\nDone. Slide-facts manifest written to:\n  {handoff_path}\n"
          f"Figures are in:\n  {out_dir}/extracted/<reading_id>/figures/\n"
          f"Upload the manifest (and figures folder, if you want figures pulled into the deck) "
          f"back into the chat with Claude and ask it to build the PowerPoint.\n\n"
          f"Once the deck exists and its outline has a '## Appendix Requests' block, run:\n"
          f"  python skills/appendix_writer.py --out-dir {out_dir} --outline <path-to-outline.md>\n"
          f"to generate targeted extended notes for just what the deck actually needs elaborated.\n{'='*70}")


if __name__ == "__main__":
    main()
