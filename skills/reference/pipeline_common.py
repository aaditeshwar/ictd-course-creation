"""Shared paths and .env loading for skills/ pipeline scripts."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_config import (  # noqa: E402
    load_dotenv,
    get_anthropic_model,
    get_ollama_base_url,
    get_ollama_generate_url,
    get_ollama_model,
    get_ollama_timeout,
    get_alignment_backend,
)

DEFAULT_READINGS = PROJECT_ROOT / "data" / "readings.json"
DEFAULT_EXAMPLES = PROJECT_ROOT / "data" / "examples.json"
# NEW: needed by topic_content_extractor.py / run_lecture_prep.py for topic names, sequence
# order (for appendix.md section ordering), and topic descriptions (reduce-prompt context).
DEFAULT_FRAMEWORK = PROJECT_ROOT / "data" / "framework.json"
DEFAULT_BOOK_CONCEPT_MAP = Path(
    r"c:\aaditeshwar\personal\transfer\papers\tech for dev\book 2020"
    r"\post publication feedback\summary for llm context"
    r"\00_COMBINED_All_Chapters_and_Concept_Map.md"
)
DEFAULT_CORE_STACK_TOPIC_MAP = Path(
    r"c:\aaditeshwar\personal\transfer\papers\tech for dev\book 2020"
    r"\post publication feedback\summary for llm context"
    r"\CoRE_Stack_Computing_Elements.md"
)
DEFAULT_LECTURE_PREP_OUT_DIR = PROJECT_ROOT / "data" / "lecture-prep"
LECTURE_PREP_INDEX = DEFAULT_LECTURE_PREP_OUT_DIR / "index.json"
LECTURE_PREP_SLUG_MAX_PREFIX = 40
LECTURE_PREP_HASH_LEN = 12
PDF_MATCH_PREFIX_LEN = 40
PDF_MATCH_MIN_PREFIX = 30

# NEW: section-chunking tunables (topic_content_extractor.py map phase)
MIN_HEADINGS_FOR_STRUCTURED_SPLIT = 2  # below this, treat heading-detection as having failed
HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
PAGE_MARKER_PATTERN = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)


def lecture_prep_hash(example_id):
    return hashlib.sha256(example_id.encode()).hexdigest()[:LECTURE_PREP_HASH_LEN]


def lecture_prep_slug(example_id):
    """Readable short name: truncated example_id + hash suffix for uniqueness."""
    digest = lecture_prep_hash(example_id)
    if len(example_id) <= LECTURE_PREP_SLUG_MAX_PREFIX:
        prefix = example_id
    else:
        prefix = example_id[:LECTURE_PREP_SLUG_MAX_PREFIX].rstrip("_")
    return f"{prefix}_{digest}"


def resolve_lecture_prep_out_dir(example_id, out_dir_override=None):
    """Pick output dir: explicit override, registered/indexed path, legacy long path, or slug dir."""
    if out_dir_override:
        return Path(out_dir_override)
    base = DEFAULT_LECTURE_PREP_OUT_DIR
    slug_dir = base / lecture_prep_slug(example_id)
    legacy_dir = base / example_id

    if LECTURE_PREP_INDEX.is_file():
        index = json.loads(LECTURE_PREP_INDEX.read_text(encoding="utf-8"))
        entry = index.get(example_id) or {}
        registered = entry.get("out_dir")
        if registered:
            registered_path = PROJECT_ROOT / registered
            if registered_path.is_dir():
                return registered_path

    if slug_dir.is_dir() and (slug_dir / "access_manifest.json").is_file():
        return slug_dir
    if legacy_dir.is_dir() and (legacy_dir / "access_manifest.json").is_file():
        return legacy_dir
    return slug_dir


def register_lecture_prep_dir(example_id, case_study_name, out_dir):
    index = {}
    if LECTURE_PREP_INDEX.is_file():
        index = json.loads(LECTURE_PREP_INDEX.read_text(encoding="utf-8"))
    try:
        rel = Path(out_dir).resolve().relative_to(PROJECT_ROOT.resolve())
        rel_str = rel.as_posix()
    except ValueError:
        rel_str = str(out_dir)
    index[example_id] = {
        "slug": lecture_prep_slug(example_id),
        "hash": lecture_prep_hash(example_id),
        "name": case_study_name,
        "out_dir": rel_str,
    }
    LECTURE_PREP_INDEX.parent.mkdir(parents=True, exist_ok=True)
    LECTURE_PREP_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")


def ensure_pdfs_dir(pdf_dir):
    """Create pdfs/ and ensure the current user can write to it (Windows ACL fix)."""
    pdf_path = Path(pdf_dir)
    pdf_path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        return pdf_path
    username = os.environ.get("USERNAME")
    if username:
        subprocess.run(
            ["icacls", str(pdf_path), "/grant", f"{username}:(OI)(CI)F", "/T"],
            capture_output=True,
            text=True,
            check=False,
        )
    return pdf_path


def ensure_lecture_prep_dirs(out_dir):
    """Create lecture-prep output dir and pdfs/ subfolder."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    return ensure_pdfs_dir(out_path / "pdfs")


def uses_core_stack_alignment(reading):
    """Background-domain (area-agnostic) and cs_fundamentals readings use the CoRE stack prompt."""
    topics = set(reading.get("topics") or [])
    if "cs_fundamentals" in topics:
        return True
    return bool(reading.get("area_agnostic"))


def pdf_path_for_reading(out_dir, reading_id):
    """Canonical expected PDF path (full reading_id filename)."""
    return os.path.join(out_dir, "pdfs", f"{reading_id}.pdf")


def pdf_stem_matches_reading(stem, reading_id):
    """True when an on-disk PDF stem matches a reading id (exact or prefix overlap)."""
    if stem == reading_id:
        return True
    n = min(len(stem), len(reading_id), PDF_MATCH_PREFIX_LEN)
    return n >= PDF_MATCH_MIN_PREFIX and stem[:n] == reading_id[:n]


def find_pdf_for_reading(out_dir, reading_id):
    """Resolve PDF on disk: exact filename first, then prefix match for truncated saves."""
    pdf_dir = Path(out_dir) / "pdfs"
    if not pdf_dir.is_dir():
        return None

    exact = pdf_dir / f"{reading_id}.pdf"
    if exact.is_file():
        return str(exact)

    matches = [
        path for path in pdf_dir.glob("*.pdf")
        if pdf_stem_matches_reading(path.stem, reading_id)
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return str(matches[0])
    return str(max(matches, key=lambda p: len(p.stem)))


def reading_has_pdf(out_dir, reading_id):
    return find_pdf_for_reading(out_dir, reading_id) is not None


def readings_missing_pdf(manifest, out_dir):
    """Non-video readings with no PDF on disk yet."""
    missing = []
    for entry in manifest.get("readings", []):
        if entry.get("access_status") == "video_no_pdf":
            continue
        if not reading_has_pdf(out_dir, entry["id"]):
            missing.append(entry)
    return missing


def refresh_manifest_pdf_status(manifest, out_dir):
    """Mark entries downloaded when a PDF file is present (resume after manual fetch)."""
    for entry in manifest.get("readings", []):
        if entry.get("access_status") == "video_no_pdf":
            continue
        pdf_path = find_pdf_for_reading(out_dir, entry["id"])
        if pdf_path:
            entry["access_status"] = "downloaded"
            entry["pdf_path"] = pdf_path
            entry.pop("note", None)
    return manifest


def require_anthropic_key():
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY not set. Add it to .env (see .env.example) or export it in your shell."
        )


# ============================================================================
# NEW: section chunking for topic_content_extractor.py's map phase.
# ============================================================================

def _strip_page_markers(text):
    return PAGE_MARKER_PATTERN.sub("", text).strip()


def _page_number_at(text, offset):
    """Last <!-- page N --> marker at or before `offset` in `text`; None if none precede it."""
    last = None
    for m in PAGE_MARKER_PATTERN.finditer(text, 0, offset + 1):
        last = int(m.group(1))
    return last


def _split_by_headings(md_text):
    """Split on markdown heading lines (#, ##, ###). Returns [] if fewer than
    MIN_HEADINGS_FOR_STRUCTURED_SPLIT headings are found -- caller falls back to fixed windows."""
    matches = list(HEADING_PATTERN.finditer(md_text))
    if len(matches) < MIN_HEADINGS_FOR_STRUCTURED_SPLIT:
        return []

    sections = []
    # content before the first heading -- keep only if it's substantial (e.g. abstract/title
    # block text that a strict heading-only split would otherwise silently drop)
    preamble = md_text[:matches[0].start()].strip()
    preamble = _strip_page_markers(preamble)
    if len(preamble) > 200:
        sections.append(("Front matter (before first heading)", preamble))

    for i, m in enumerate(matches):
        heading_text = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        body = _strip_page_markers(md_text[start:end])
        if body:
            sections.append((heading_text, body))
    return sections


def _split_by_fixed_windows(md_text, fallback_window_pages=3, overlap_pages=1):
    """Fallback when heading detection fails: group pages (from <!-- page N --> markers) into
    fixed-size windows with slight overlap, e.g. "Pages 1-3", "Pages 3-5", ..."""
    markers = [(int(m.group(1)), m.start()) for m in PAGE_MARKER_PATTERN.finditer(md_text)]
    if not markers:
        # no page markers at all (shouldn't happen if pdf_to_text_figures.py wrote them, but
        # degrade gracefully) -- treat the whole document as one window.
        stripped = _strip_page_markers(md_text)
        return [("Full text (no page markers found)", stripped)] if stripped else []

    max_page = markers[-1][0]
    windows = []
    start_page = 1
    while start_page <= max_page:
        end_page = min(start_page + fallback_window_pages - 1, max_page)
        start_offset = next((off for pg, off in markers if pg == start_page), markers[0][1])
        # end offset = start of the marker for (end_page + 1), or end of doc
        next_page_marker = next(((pg, off) for pg, off in markers if pg == end_page + 1), None)
        end_offset = next_page_marker[1] if next_page_marker else len(md_text)
        chunk_text = _strip_page_markers(md_text[start_offset:end_offset])
        if chunk_text:
            windows.append((f"Pages {start_page}-{end_page}", chunk_text))
        if end_page >= max_page:
            break
        start_page = max(end_page - overlap_pages + 1, start_page + 1)
    return windows


def get_section_chunks(text_md_path, fallback_window_pages=3, overlap_pages=1):
    """
    Split a pymupdf4llm-produced markdown file (with <!-- page N --> markers, written by
    pdf_to_text_figures.py) into (section_name, section_text) pairs.

    Tries heading-based splitting first (real ## section names -- accurate location_hints for
    the map/reduce prompts). Falls back to fixed page windows if fewer than
    MIN_HEADINGS_FOR_STRUCTURED_SPLIT headings are detected (heading-detection failure on an
    unconventionally-styled paper, e.g. two-column layouts pymupdf4llm's font-size heuristic
    doesn't handle well).

    Returns [] if the file is missing or empty -- caller should treat that as "no text available"
    the same way get_reading_text() already does for the plain-text path.
    """
    if not text_md_path or not os.path.isfile(text_md_path):
        return []
    with open(text_md_path, encoding="utf-8") as f:
        md_text = f.read()
    if not md_text.strip():
        return []

    sections = _split_by_headings(md_text)
    if sections:
        return sections
    return _split_by_fixed_windows(md_text, fallback_window_pages, overlap_pages)
