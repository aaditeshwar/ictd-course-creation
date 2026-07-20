"""Shared paths and .env loading for skills/ pipeline scripts."""
import os
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


def uses_core_stack_alignment(reading):
    """Background-domain (area-agnostic) and cs_fundamentals readings use the CoRE stack prompt."""
    topics = set(reading.get("topics") or [])
    if "cs_fundamentals" in topics:
        return True
    return bool(reading.get("area_agnostic"))


def pdf_path_for_reading(out_dir, reading_id):
    return os.path.join(out_dir, "pdfs", f"{reading_id}.pdf")


def readings_missing_pdf(manifest, out_dir):
    """Non-video readings with no PDF on disk yet."""
    missing = []
    for entry in manifest.get("readings", []):
        if entry.get("access_status") == "video_no_pdf":
            continue
        if not os.path.isfile(pdf_path_for_reading(out_dir, entry["id"])):
            missing.append(entry)
    return missing


def refresh_manifest_pdf_status(manifest, out_dir):
    """Mark entries downloaded when a PDF file is present (resume after manual fetch)."""
    for entry in manifest.get("readings", []):
        if entry.get("access_status") == "video_no_pdf":
            continue
        pdf_path = pdf_path_for_reading(out_dir, entry["id"])
        if os.path.isfile(pdf_path):
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
