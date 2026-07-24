"""Shared LLM configuration loaded from .env (project root)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OLLAMA_BASE_URL = "http://100.102.70.41:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:14b"
DEFAULT_OLLAMA_TIMEOUT = 120
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ALIGNMENT_BACKEND = "anthropic"


def load_dotenv(env_path=None):
    """Load KEY=VALUE pairs from .env into os.environ (does not override existing vars)."""
    path = Path(env_path) if env_path else PROJECT_ROOT / ".env"
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
    return True


def get_ollama_base_url():
    load_dotenv()
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def get_ollama_generate_url():
    return f"{get_ollama_base_url()}/api/generate"


def get_ollama_model():
    load_dotenv()
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def get_ollama_timeout():
    load_dotenv()
    return int(os.environ.get("OLLAMA_TIMEOUT", str(DEFAULT_OLLAMA_TIMEOUT)))


def get_anthropic_model():
    load_dotenv()
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)


def get_alignment_backend():
    load_dotenv()
    return os.environ.get("ALIGNMENT_BACKEND", DEFAULT_ALIGNMENT_BACKEND).strip().lower()


def get_map_backend():
    load_dotenv()
    raw = os.environ.get("MAP_BACKEND") or os.environ.get("ALIGNMENT_BACKEND", DEFAULT_ALIGNMENT_BACKEND)
    return raw.strip().lower()


def get_reduce_backend():
    load_dotenv()
    raw = os.environ.get("REDUCE_BACKEND") or os.environ.get("ALIGNMENT_BACKEND", DEFAULT_ALIGNMENT_BACKEND)
    return raw.strip().lower()
