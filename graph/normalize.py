"""
normalize.py
------------
Normalisierung von Entitaets- und Relationsnamen, damit z.B. "IL-6" und
"Interleukin-6 (IL-6)" oder "Muskeln" und "Muskulatur" auf denselben Knoten
abgebildet werden - aber "Typ-I-Diabetes" und "Typ-II-Diabetes" nicht.

Zwei Stufen, komplett lokal ueber Ollama:
1. Kandidatensuche per Embedding (bge-m3, Kosinus-Aehnlichkeit). Die Werte
   ueberlappen stark (Typ-I/Typ-II-Diabetes 0.92 = verschieden, MS/Multiple
   Sklerose 0.59 = gleich), ein Schwellenwert allein trennt daher nicht -
   er dient nur als grober Filter.
2. Entscheidung durch das LLM (prompts/normalize_judge.md): dieselbe Entitaet
   oder nur verwandt? Nur bei "gleich" wird auf den bekannten Begriff gemappt.

Voraussetzung: 'ollama pull bge-m3'.
"""

import math
import os
from functools import lru_cache
from typing import Optional

import ollama

EMBED_MODEL = "bge-m3"
JUDGE_MODEL = "gemma4:26b"
CANDIDATE_THRESHOLD = 0.55
MAX_CANDIDATES = 5
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "normalize_judge.md")


def _cosine_similarity(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


@lru_cache(maxsize=4096)
def _embed(text: str) -> tuple:
    """Embeddet einen Begriff, gecacht damit jeder Begriff nur einmal berechnet wird."""
    return tuple(ollama.embed(model=EMBED_MODEL, input=text)["embeddings"][0])


@lru_cache(maxsize=4096)
def _judge(term: str, candidates: tuple) -> Optional[str]:
    """Fragt das LLM, welcher Kandidat (falls einer) dieselbe Entitaet wie 'term' ist."""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    prompt = template.format(term=term, candidates="\n".join(f"- {c}" for c in candidates))
    response = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=False,
        options={"num_predict": 100, "temperature": 0},
    )
    answer = response["message"]["content"].strip().strip('"').strip("'")
    return answer if answer in candidates else None


def find_match(term: str, known_terms: list) -> Optional[str]:
    """
    Gibt den bekannten Begriff zurueck, der dieselbe Entitaet wie 'term'
    bezeichnet, oder None, falls 'term' neu ist.
    """
    if term in known_terms:
        return term
    lowered = {k.lower().strip(): k for k in known_terms}
    if term.lower().strip() in lowered:
        return lowered[term.lower().strip()]

    term_vec = _embed(term)
    scored = sorted(
        ((_cosine_similarity(term_vec, _embed(k)), k) for k in known_terms),
        reverse=True,
    )
    candidates = tuple(k for score, k in scored[:MAX_CANDIDATES] if score >= CANDIDATE_THRESHOLD)
    if not candidates:
        return None
    return _judge(term, candidates)


def normalize_triple(triple: dict, known_entities: list, known_relations: list) -> dict:
    """
    Ersetzt subject/object/relation im Tripel durch den kanonischen,
    bereits bekannten Begriff, falls das LLM sie als identisch bestaetigt.
    Modifiziert eine Kopie, nicht das Original.
    """
    normalized = dict(triple)
    normalized["subject"] = find_match(triple["subject"], known_entities) or triple["subject"]
    normalized["object"] = find_match(triple["object"], known_entities) or triple["object"]
    normalized["relation"] = find_match(triple["relation"], known_relations) or triple["relation"]
    return normalized
