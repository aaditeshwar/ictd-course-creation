"""Shared paths and .env loading for skills/ pipeline scripts."""
import hashlib
import json
import os
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

