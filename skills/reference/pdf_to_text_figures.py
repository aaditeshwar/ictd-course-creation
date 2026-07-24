"""
Step 2 of the lecture-prep pipeline: convert every PDF in <out-dir>/pdfs/ to plain text
(per-page) AND to structured markdown (for section-aware chunking), and extract embedded
images with a best-effort caption guess for each.

Install: pip install pymupdf pymupdf4llm

Usage:
    python pdf_to_text_figures.py --out-dir ./data/<example-id>

Reads:
    <out-dir>/pdfs/<reading_id>.pdf   (whatever resolve_and_download.py put there, or that you
                                        manually dropped in following manual_downloads_needed.md)
Writes:
    <out-dir>/extracted/<reading_id>/text.txt          -- full plain text, page breaks marked
                                                            (fallback source; also what
                                                            book_alignment_scorer.py still reads)
    <out-dir>/extracted/<reading_id>/text.md            -- NEW: pymupdf4llm markdown, with
                                                            <!-- page N --> markers and detected
                                                            headings -- primary input for
                                                            topic_content_extractor.py's
                                                            section-aware chunking
                                                            (pipeline_common.get_section_chunks)
    <out-dir>/extracted/<reading_id>/figures/fig_N.png  -- extracted images (JPX/JP2 saved as PNG)
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
import pymupdf4llm

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pipeline_common import find_pdf_for_reading  # noqa: E402

CAPTION_PATTERN = re.compile(r"(Figure|Fig\.?)\s*\d+[:.]?\s*[^\n]{0,200}", re.IGNORECASE)
JPX_EXTENSIONS = frozenset({"jpx", "jp2", "j2k"})


def save_figure_image(doc, xref, img_bytes, ext, fig_dir, page_num, img_idx):
    """Write an extracted image; JPX/JP2/J2K are converted to PNG."""
    ext_lower = ext.lower()
    if ext_lower in JPX_EXTENSIONS:
        fname = f"page{page_num}_img{img_idx}.png"
        fpath = os.path.join(fig_dir, fname)
        pix = fitz.Pixmap(doc, xref)
        try:
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pix.save(fpath)
        finally:
            pix = None
        return fpath

    fname = f"page{page_num}_img{img_idx}.{ext}"
    fpath = os.path.join(fig_dir, fname)
    with open(fpath, "wb") as f:
        f.write(img_bytes)
    return fpath


def extract_markdown(pdf_path):
    """
    pymupdf4llm.to_markdown with page_chunks=True gives one dict per page (with a 'text' key
    already in markdown, headings included where font-size/boldness heuristics detect them).
    We re-join with explicit <!-- page N --> markers so pipeline_common.get_section_chunks can
    do both heading-based splitting AND page-window fallback from the same file.
    """
    page_dicts = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
    parts = []
    for i, page in enumerate(page_dicts, start=1):
        page_text = page.get("text", "") if isinstance(page, dict) else str(page)
        parts.append(f"<!-- page {i} -->\n{page_text}")
    return "\n\n".join(parts)


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
            try:
                fpath = save_figure_image(doc, xref, img_bytes, ext, fig_dir, page_num, img_idx)
            except Exception:
                continue

            # best-effort caption: nearest caption-like text found on the same page, else None.
            # This is a heuristic (position-blind) -- for a paper with multiple figures per page,
            # verify captions manually; good enough for a first pass.
            caption_guess = captions_on_page[min(img_idx, len(captions_on_page) - 1)] if captions_on_page else None

            figures.append({
                "file": os.path.relpath(fpath, out_dir),
                "page": page_num,
                "caption_guess": caption_guess,
            })

    plain_text = "".join(full_text)
    with open(os.path.join(out_dir, "text.txt"), "w", encoding="utf-8") as f:
        f.write(plain_text)

    # NEW: markdown extraction for section-aware chunking. Best-effort -- if pymupdf4llm chokes
    # on a malformed PDF, don't fail the whole extraction step over it; text.txt/figures still
    # get written, and topic_content_extractor.py will fall back to abstract-only for this
    # reading (same degradation path as a reading with no PDF at all).
    md_text = None
    md_error = None
    try:
        md_text = extract_markdown(pdf_path)
        with open(os.path.join(out_dir, "text.md"), "w", encoding="utf-8") as f:
            f.write(md_text)
    except Exception as e:
        md_error = str(e)

    with open(os.path.join(out_dir, "figures.json"), "w", encoding="utf-8") as f:
        json.dump(figures, f, indent=2)

    doc.close()
    return len(plain_text), len(figures), (md_text is not None), md_error


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
            text_len, n_figs, md_ok, md_error = extract_pdf(pdf_path, out_dir)
        except Exception as e:
            print(f"  FAILED: {e}")
            entry["extraction_error"] = str(e)
            continue
        entry["access_status"] = "extracted"
        entry["text_path"] = os.path.join(out_dir, "text.txt")
        entry["figures_path"] = os.path.join(out_dir, "figures.json")
        entry["n_figures_extracted"] = n_figs
        if md_ok:
            entry["text_md_path"] = os.path.join(out_dir, "text.md")
        else:
            entry.pop("text_md_path", None)
            entry["text_md_error"] = md_error
            print(f"  WARNING: markdown extraction failed ({md_error}) -- "
                  f"topic_content_extractor.py will fall back to abstract-only for this reading")
        md_note = "text.md ok" if md_ok else "text.md FAILED"
        print(f"  {text_len} chars of text, {n_figs} figures, {md_note}")

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest updated: {manifest_path}")


if __name__ == "__main__":
    main()
