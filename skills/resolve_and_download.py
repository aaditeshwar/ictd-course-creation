"""
Step 1 of the lecture-prep pipeline: for every reading in a given case study, figure out what's
downloadable automatically vs. what needs manual (institutional-access) download.

Install: pip install requests

Usage:
    python skills/resolve_and_download.py --example-id gov_egovernance_accountability

Defaults: data/examples.json, data/readings.json, output under data/lecture-prep/<example-id>/

Writes:
    <out-dir>/pdfs/<reading_id>.pdf         -- for everything successfully auto-downloaded
    <out-dir>/manual_downloads_needed.md    -- checklist for the rest, with DOI/search links
    <out-dir>/access_manifest.json          -- machine-readable status per reading, consumed by
                                                the next pipeline step
"""
import json
import re
import time
import argparse
import os
from pathlib import Path
import requests

from pipeline_common import (
    DEFAULT_READINGS,
    DEFAULT_EXAMPLES,
    resolve_lecture_prep_out_dir,
    register_lecture_prep_dir,
    ensure_lecture_prep_dirs,
    find_pdf_for_reading,
    pdf_path_for_reading,
    PDF_MATCH_MIN_PREFIX,
    refresh_manifest_pdf_status,
)

HEADERS = {"User-Agent": "ictd-lecture-prep/1.0 (mailto:you@example.com)"}
REQUEST_DELAY = 1.0


def load_case_study(examples_path, readings_path, example_id):
    with open(examples_path, encoding="utf-8") as f:
        examples = json.load(f)
    with open(readings_path, encoding="utf-8") as f:
        readings_by_id = {r["id"]: r for r in json.load(f)["readings"]}

    cs = next((c for c in examples["case_studies"] if c["id"] == example_id), None)
    if cs is None:
        available = [c["id"] for c in examples["case_studies"]]
        raise SystemExit(f"Unknown example id '{example_id}'. Available: {available}")

    readings = [readings_by_id[rid] for rid in cs["readings"] if rid in readings_by_id]
    return cs, readings


def looks_like_open_pdf(url):
    if not url:
        return False
    # heuristics: arxiv, preprint S3 buckets, .pdf extension, gov.uk, direct-hosted PDFs are
    # usually fetchable; ACM DL / JSTOR / AEA / Springer / ScienceDirect / IEEE Xplore are not
    blocked_domains = ["dl.acm.org", "jstor.org", "aeaweb.org", "link.springer.com",
                       "sciencedirect.com", "ieeexplore.ieee.org", "researchgate.net",
                       "sagepub.com", "cambridge.org", "harpercollins", "bloomsbury.com",
                       "panmacmillan.com", "ted.com", "youtube.com", "youtu.be"]
    if any(d in url for d in blocked_domains):
        return False
    return url.endswith(".pdf") or "arxiv.org" in url or "preprints" in url or "s3" in url


def try_resolve_doi_via_crossref(title):
    """For readings with no link at all -- try Crossref to at least get a DOI + confirm it's a
    real paywalled record (better than nothing for the manual-download checklist)."""
    try:
        r = requests.get("https://api.crossref.org/works",
                          params={"query.bibliographic": title, "rows": 1},
                          headers=HEADERS, timeout=15)
        time.sleep(REQUEST_DELAY)
        items = r.json().get("message", {}).get("items", [])
        if items:
            return items[0].get("DOI")
    except requests.RequestException:
        pass
    return None


def download_pdf(url, dest_path):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        time.sleep(REQUEST_DELAY)
        if r.status_code == 200 and r.headers.get("content-type", "").lower().startswith(("application/pdf", "binary")):
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return True
        # some hosts don't set content-type correctly -- fall back to checking magic bytes
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return True
    except requests.RequestException:
        pass
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--example-id", required=True)
    parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    parser.add_argument("--readings", default=str(DEFAULT_READINGS))
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    out_dir = str(resolve_lecture_prep_out_dir(args.example_id, args.out_dir))
    cs, readings = load_case_study(args.examples, args.readings, args.example_id)
    register_lecture_prep_dir(args.example_id, cs["name"], out_dir)
    pdf_dir = ensure_lecture_prep_dirs(out_dir)
    print(f"Output dir: {out_dir}")
    print(f"Save manual PDFs here: {pdf_dir}")
    print(f"Case study: {cs['name']} ({len(readings)} readings)")

    manifest = []
    manual_needed = []

    for r in readings:
        entry = {"id": r["id"], "title": r["title"], "authors": r.get("authors"),
                  "year": r.get("year"), "venue": r.get("venue")}

        link = r.get("link")
        doi = r.get("doi")
        is_video = link and ("youtube.com" in link or "youtu.be" in link or "ted.com" in link)

        if is_video:
            entry["access_status"] = "video_no_pdf"
            entry["note"] = "Video/talk -- use abstract/description text or a transcript, no PDF to extract."
            manifest.append(entry)
            continue

        candidate_url = None
        if doi:
            candidate_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        elif link:
            candidate_url = link

        if candidate_url and looks_like_open_pdf(candidate_url):
            dest = os.path.join(pdf_dir, f"{r['id']}.pdf")
            if os.path.isfile(dest):
                print(f"  Using existing PDF: {r['id']}")
                entry["access_status"] = "downloaded"
                entry["pdf_path"] = dest
                manifest.append(entry)
                continue
            print(f"  Attempting auto-download: {r['id']} <- {candidate_url}")
            ok = download_pdf(candidate_url, dest)
            if ok:
                entry["access_status"] = "downloaded"
                entry["pdf_path"] = dest
                manifest.append(entry)
                continue
            else:
                print(f"    failed, falling back to manual-download flag")

        dest = find_pdf_for_reading(out_dir, r["id"])
        if dest:
            print(f"  Using manually provided PDF: {r['id']} ({Path(dest).name})")
            entry["access_status"] = "downloaded"
            entry["pdf_path"] = dest
            manifest.append(entry)
            continue

        # not open / auto-download failed -- resolve a DOI if we don't have one, for the checklist
        resolved_doi = doi
        if not resolved_doi:
            print(f"  Resolving DOI via Crossref for manual-download checklist: {r['id']}")
            resolved_doi = try_resolve_doi_via_crossref(r["title"])

        entry["access_status"] = "needs_manual_download"
        entry["doi"] = resolved_doi
        entry["existing_link"] = link
        manifest.append(entry)
        manual_needed.append(entry)

    manifest_data = {"case_study_id": args.example_id, "readings": manifest}
    refresh_manifest_pdf_status(manifest_data, out_dir)
    manifest = manifest_data["readings"]
    manual_needed = [e for e in manifest if e["access_status"] == "needs_manual_download"]

    with open(os.path.join(out_dir, "access_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    with open(os.path.join(out_dir, "manual_downloads_needed.md"), "w", encoding="utf-8") as f:
        f.write(f"# Manual downloads needed for: {cs['name']}\n\n")
        f.write(f"Save each PDF to `{pdf_dir}\\` using the reading id as the filename.\n")
        f.write(f"Truncated names are OK if the first {PDF_MATCH_MIN_PREFIX} characters match "
                f"(e.g. browser saving `..._natural_resource_man.pdf` for a longer id).\n\n")
        f.write(f"    {pdf_dir}\\<reading_id>.pdf\n\n")
        f.write(f"Use institutional access (IIT Delhi library / ACM DL / JSTOR / AEA), then re-run:\n\n")
        f.write(f"    python skills/run_lecture_prep.py --example-id {args.example_id}\n\n")
        if not manual_needed:
            f.write("Nothing needed -- everything was auto-downloadable or is a video.\n")
        for e in manual_needed:
            f.write(f"## `{e['id']}`\n")
            f.write(f"- **Title**: {e['title']}\n")
            f.write(f"- **Authors**: {e.get('authors') or '(unknown)'}\n")
            f.write(f"- **Year/Venue**: {e.get('year') or '?'} / {e.get('venue') or '?'}\n")
            if e.get("doi"):
                f.write(f"- **DOI**: https://doi.org/{e['doi']}\n")
            if e.get("existing_link"):
                f.write(f"- **Existing link on record**: {e['existing_link']}\n")
            f.write(f"- **Save to**: `{pdf_dir}\\{e['id']}.pdf`\n\n")

    downloaded = sum(1 for e in manifest if e["access_status"] == "downloaded")
    videos = sum(1 for e in manifest if e["access_status"] == "video_no_pdf")
    print(f"\nDone. {downloaded} auto-downloaded, {videos} videos (no PDF needed), "
          f"{len(manual_needed)} need manual download.")
    if manual_needed:
        print(f"See {out_dir}/manual_downloads_needed.md for the checklist.")


if __name__ == "__main__":
    main()
