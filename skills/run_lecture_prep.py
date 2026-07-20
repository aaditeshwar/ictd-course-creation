"""
Orchestrates the full lecture-prep pipeline for one case study (example_id), then writes a
single consolidated manifest designed to be handed back to Claude (in a chat) to build the
PowerPoint from.

Usage:
    python skills/run_lecture_prep.py --example-id gov_egovernance_accountability

Defaults: data/examples.json, data/readings.json, instructor book concept map, CoRE stack topic
summary, output under data/lecture-prep/<example-id>/.

This runs resolve_and_download.py, stops if any non-video readings still lack a PDF (see
manual_downloads_needed.md), then pdf_to_text_figures.py, book_alignment_scorer.py, and writes:

    data/lecture-prep/<example-id>/lecture_prep_manifest.json

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
    DEFAULT_BOOK_CONCEPT_MAP,
    DEFAULT_CORE_STACK_TOPIC_MAP,
    DEFAULT_LECTURE_PREP_OUT_DIR,
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
        help="alignment scorer backend (default: ALIGNMENT_BACKEND from .env)",
    )
    parser.add_argument(
        "--force-alignment",
        action="store_true",
        help="re-score all readings even if book_alignment.json cache exists",
    )
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

    # ---------------- consolidate into the final handoff manifest ----------------
    with open(args.examples, encoding="utf-8") as f:
        examples = json.load(f)
    cs = next(c for c in examples["case_studies"] if c["id"] == args.example_id)

    manifest = load_manifest(out_dir)
    with open(os.path.join(out_dir, "book_alignment.json"), encoding="utf-8") as f:
        alignment = json.load(f)

    for entry in manifest["readings"]:
        entry["book_alignment"] = alignment.get(entry["id"], {})
        if entry.get("figures_path") and os.path.exists(entry["figures_path"]):
            with open(entry["figures_path"], encoding="utf-8") as f:
                entry["figures"] = json.load(f)

    handoff = {
        "case_study": cs,
        "readings": sorted(
            manifest["readings"],
            key=lambda e: e.get("book_alignment", {}).get("alignment_score") or 0,
            reverse=True,
        ),
    }
    handoff_path = os.path.join(out_dir, "lecture_prep_manifest.json")
    with open(handoff_path, "w", encoding="utf-8") as f:
        json.dump(handoff, f, indent=2)

    print(f"\n{'='*70}\nDone. Handoff manifest written to:\n  {handoff_path}\n"
          f"Figures are in:\n  {out_dir}/extracted/<reading_id>/figures/\n"
          f"Upload the manifest (and figures folder, if you want figures pulled into the deck) "
          f"back into the chat with Claude and ask it to build the PowerPoint.\n{'='*70}")


if __name__ == "__main__":
    main()
