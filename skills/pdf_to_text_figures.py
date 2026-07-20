"""
Step 2 of the lecture-prep pipeline: convert every PDF in <out-dir>/pdfs/ to plain text
(per-page) and extract embedded images, with a best-effort caption guess for each.

Install: pip install pymupdf

Usage:
    python pdf_to_text_figures.py --out-dir ./data/<example-id>

Reads:
    <out-dir>/pdfs/<reading_id>.pdf   (whatever resolve_and_download.py put there, or that you
                                        manually dropped in following manual_downloads_needed.md)
Writes:
    <out-dir>/extracted/<reading_id>/text.txt          -- full text, page breaks marked
    <out-dir>/extracted/<reading_id>/figures/fig_N.png  -- extracted images
    <out-dir>/extracted/<reading_id>/figures.json       -- [{file, page, caption_guess}]
    <out-dir>/access_manifest.json                      -- updated in place with text/figure paths
"""
import os
import re
import json
import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pipeline_common import find_pdf_for_reading  # noqa: E402

CAPTION_PATTERN = re.compile(r"(Figure|Fig\.?)\s*\d+[:.]?\s*[^\n]{0,200}", re.IGNORECASE)


def extract_pdf(pdf_path, out_dir):
    doc = fitz.open(pdf_path)
    full_text = []
    figures = []

    fig_dir = os.path.join(out_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        full_text.append(f"\n--- page {page_num} ---\n{text}")

        # find caption-looking text on this page, to pair with any images found on it
        captions_on_page = CAPTION_PATTERN.findall(text)
        # CAPTION_PATTERN.findall with groups returns only the group; redo with finditer for full match
        captions_on_page = [m.group(0) for m in CAPTION_PATTERN.finditer(text)]

        images = page.get_images(full=True)
        for img_idx, img in enumerate(images):
            xref = img[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue
            img_bytes = base_image["image"]
            ext = base_image["ext"]
            fname = f"page{page_num}_img{img_idx}.{ext}"
            fpath = os.path.join(fig_dir, fname)
            with open(fpath, "wb") as f:
                f.write(img_bytes)

            # best-effort caption: nearest caption-like text found on the same page, else None.
            # This is a heuristic (position-blind) -- for a paper with multiple figures per page,
            # verify captions manually; good enough for a first pass.
            caption_guess = captions_on_page[min(img_idx, len(captions_on_page) - 1)] if captions_on_page else None

            figures.append({
                "file": os.path.relpath(fpath, out_dir),
                "page": page_num,
                "caption_guess": caption_guess,
            })

    with open(os.path.join(out_dir, "text.txt"), "w", encoding="utf-8") as f:
        f.write("".join(full_text))
    with open(os.path.join(out_dir, "figures.json"), "w", encoding="utf-8") as f:
        json.dump(figures, f, indent=2)

    doc.close()
    return len("".join(full_text)), len(figures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    pdf_dir = os.path.join(args.out_dir, "pdfs")
    extracted_root = os.path.join(args.out_dir, "extracted")
    manifest_path = os.path.join(args.out_dir, "access_manifest.json")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    if not os.path.isdir(pdf_dir):
        raise SystemExit(f"No pdfs/ directory found at {pdf_dir} -- run resolve_and_download.py first.")

    for entry in manifest["readings"]:
        pdf_path = find_pdf_for_reading(args.out_dir, entry["id"])
        if not pdf_path:
            continue  # video, or still needs manual download -- skip silently, that's expected
        out_dir = os.path.join(extracted_root, entry["id"])
        os.makedirs(out_dir, exist_ok=True)
        if Path(pdf_path).stem != entry["id"]:
            print(f"Extracting: {entry['id']} (from {Path(pdf_path).name})")
        else:
            print(f"Extracting: {entry['id']}")
        try:
            text_len, n_figs = extract_pdf(pdf_path, out_dir)
        except Exception as e:
            print(f"  FAILED: {e}")
            entry["extraction_error"] = str(e)
            continue
        entry["access_status"] = "extracted"
        entry["text_path"] = os.path.join(out_dir, "text.txt")
        entry["figures_path"] = os.path.join(out_dir, "figures.json")
        entry["n_figures_extracted"] = n_figs
        print(f"  {text_len} chars of text, {n_figs} figures")

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest updated: {manifest_path}")


if __name__ == "__main__":
    main()
