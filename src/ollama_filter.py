"""
Uses a local Ollama model to:
  1. Decide if a paper is relevant to the course (developing-regions context required for all
     topics EXCEPT cs_fundamentals, where transferable methodology is enough regardless of
     study-site geography -- see framework.json area_agnostic_topic_vector).
  2. Suggest areas / topics / cross_cutting_axes tags from framework.json's controlled vocabulary.

Install: pip install requests

Configure via .env (see .env.example):
  OLLAMA_BASE_URL=http://100.102.70.41:11434
  OLLAMA_MODEL=qwen2.5:14b
  OLLAMA_TIMEOUT=120
"""
import json
import re

from src.llm_config import get_ollama_model, get_ollama_timeout
from src.ollama_client import ollama_generate


def load_framework(path="data/framework.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_taxonomy_block(fw):
    lines = ["AREAS:"]
    for a in fw["areas"]:
        lines.append(f"- {a['id']}: {a['name']} -- {a['description'][:200]}")
    lines.append("\nTOPICS:")
    for t in fw["topics"]:
        lines.append(f"- {t['id']}: {t['name']} -- {t['description'][:200]}")
    lines.append("\nCROSS_CUTTING_AXES:")
    for x in fw["cross_cutting_axes"]:
        lines.append(f"- {x['id']}: {x['name']} -- {x['description'][:150]}")
    return "\n".join(lines)


PROMPT_TEMPLATE = """You are screening academic papers for an IIT Delhi course on ICT for \
Development and Sustainability (rural/developing-regions focus, India-centric).

{taxonomy}

RULE: For topic "cs_fundamentals", the paper does NOT need to be set in a developing region -- \
general-purpose methodology that could be *adapted* to a developing-regions context counts as \
relevant. For every OTHER topic, the paper must substantively engage a developing-regions \
context (India or other low/middle-income country settings, informal economies, low-resource \
settings, etc.) to be relevant.

PAPER:
Title: {title}
Authors: {authors}
Abstract: {abstract}

Respond with ONLY a JSON object, no other text, in this exact shape:
{{
  "relevant": true or false,
  "reason": "one sentence justifying the decision, citing the specific rule applied",
  "areas": ["<area_id>", ...],   // empty list ok if genuinely area-agnostic or no fit
  "topics": ["<topic_id>", ...],  // at least one if relevant=true
  "cross_cutting_axes": ["<axis_id>", ...],  // empty list ok
  "area_agnostic": true or false
}}
"""


def classify_paper(paper, taxonomy_block, model=None, timeout=None):
    prompt = PROMPT_TEMPLATE.format(
        taxonomy=taxonomy_block,
        title=paper.get("title", ""),
        authors=paper.get("authors", ""),
        abstract=(paper.get("abstract") or "(no abstract available -- judge from title/authors only, "
                                            "be more conservative)")[:2500],
    )
    raw = ollama_generate(
        prompt,
        model=model or get_ollama_model(),
        timeout=timeout if timeout is not None else get_ollama_timeout(),
    )
    return _extract_json(raw)


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"relevant": False, "reason": "MODEL_OUTPUT_PARSE_FAILURE", "areas": [],
                 "topics": [], "cross_cutting_axes": [], "area_agnostic": False, "_raw": text}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"relevant": False, "reason": "MODEL_OUTPUT_JSON_INVALID", "areas": [],
                 "topics": [], "cross_cutting_axes": [], "area_agnostic": False, "_raw": text}


def keyword_prefilter(paper, fw, min_hits=1):
    """
    Cheap first pass BEFORE calling the LLM: does the title+abstract contain any keyword from
    framework.json at all? This cuts obviously-irrelevant papers (e.g. pure hardware/theory
    papers with zero overlap) without spending an LLM call on every single paper.
    Returns (passed: bool, matched_keywords: list).
    """
    text = f"{paper.get('title','')} {paper.get('abstract','') or ''}".lower()
    all_keywords = []
    for bucket in (fw["areas"], fw["topics"], fw["cross_cutting_axes"]):
        for entry in bucket:
            all_keywords.extend(entry.get("keywords", []))
    matched = [kw for kw in all_keywords if kw.lower() in text]
    return (len(matched) >= min_hits), matched
