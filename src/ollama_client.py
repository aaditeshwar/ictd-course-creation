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


def extract_json_object(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
