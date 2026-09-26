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

Die Kandidatensuche vergleicht den neuen Begriff gegen ALLE bekannten
Begriffe - bei wachsendem Graphen also O(N) Vergleiche pro Tripel-Feld.
Die Kosinus-Berechnung selbst laeuft deshalb ueber NumPy (ein Matrix-Vektor-
Produkt statt einer Python-Schleife pro Begriffspaar) - das verschiebt die
Schmerzgrenze um Groessenordnungen nach hinten, macht das grundsaetzliche
O(N)-Wachstum aber nicht weg (siehe PROGRESS.md fuer den Stand dazu).

Voraussetzung: 'ollama pull bge-m3'.
"""

import os
from functools import lru_cache
from typing import Optional

import numpy as np
import ollama

EMBED_MODEL = "bge-m3"
JUDGE_MODEL = "gemma4:26b"
CANDIDATE_THRESHOLD = 0.55
MAX_CANDIDATES = 5
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "normalize_judge.md")


@lru_cache(maxsize=4096)
def _embed(text: str) -> np.ndarray:
    """Embeddet einen Begriff, gecacht damit jeder Begriff nur einmal berechnet wird."""
    vec = ollama.embed(model=EMBED_MODEL, input=text)["embeddings"][0]
    return np.array(vec, dtype=np.float32)


def _top_matches(term_vec: np.ndarray, known_terms: list) -> list:
    """
    Kosinus-Aehnlichkeit von term_vec gegen alle known_terms, vektorisiert:
    ein Matrix-Vektor-Produkt statt einer Python-Schleife mit sum()/sqrt()
    pro Begriffspaar. Gibt (score, term) absteigend sortiert zurueck.
    """
    matrix = np.stack([_embed(k) for k in known_terms])  # (N, D)
    term_norm = term_vec / (np.linalg.norm(term_vec) + 1e-12)
    matrix_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    scores = matrix_norm @ term_norm  # (N,) - eine Matrixmultiplikation statt N Python-Schleifen
    order = np.argsort(-scores)
    return [(float(scores[i]), known_terms[i]) for i in order]


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

    if not known_terms:
        return None

    term_vec = _embed(term)
    scored = _top_matches(term_vec, known_terms)
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
