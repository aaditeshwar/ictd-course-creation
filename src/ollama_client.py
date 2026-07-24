"""Thin client for Ollama /api/generate."""
import json
import re

import requests

from src.llm_config import get_ollama_generate_url, get_ollama_model, get_ollama_timeout


def ollama_generate(prompt, model=None, timeout=None, temperature=0.1, num_predict=1500):
    model = model or get_ollama_model()
    timeout = timeout if timeout is not None else get_ollama_timeout()
    resp = requests.post(
        get_ollama_generate_url(),
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _escape_control_chars_in_json_strings(raw):
    """Ollama models often emit literal newlines inside JSON string values."""
    out = []
    in_string = False
    escape = False
    for ch in raw:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            continue
        out.append(ch)
    return "".join(out)


def extract_json_object(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    blob = match.group(0)
    for candidate in (blob, _escape_control_chars_in_json_strings(blob)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
