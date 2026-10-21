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

import json
import os
from functools import lru_cache
from typing import Optional

import numpy as np
import ollama

from graph.translate import DETAIL_FIELDS, detail_to_english, to_english

EMBED_MODEL = "bge-m3"
JUDGE_MODEL = "gemma4:26b"
CANDIDATE_THRESHOLD = 0.55
# Hinweis-Schwelle fuer similar_entities(): bewusst niedrig, weil das
# Embedding Abkuerzungen schlecht erkennt ("IL6": IL-8 0.67, Interleukin-6
# 0.64). Ob ein Hinweis wirklich dieselbe Sache ist, entscheidet das
# Extraktionsmodell (Regel in polygraph/prompts/extract.md).
SIMILAR_THRESHOLD = 0.6
MAX_JUDGE_CANDIDATES = 20
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


def judge_schema(candidates: tuple) -> dict:
    """
    Structured Output fuer den Richter: erst eine kurze Begruendung, dann
    der Treffer - per enum nur einer der Kandidaten oder null, ein
    erfundener Name ist damit gar nicht erst moeglich. Auch fuer das
    erzwungene Urteil des Duplikat-Agenten (graph/dedupe.py).

    Begruendung VOR dem Treffer, weil das Modell ohne sie bei vielen
    aehnlichen Kandidaten den aehnlichsten waehlte statt zu pruefen, ob er
    wirklich dasselbe ist: "Skelettmuskel" wurde mit 2 Kandidaten korrekt
    abgelehnt (Unterbegriff), mit 9 Kandidaten aus dem echten Graphen aber
    auf "Muskeln" gemappt. Kostet ca. 1.3 s statt 0.5 s pro Entscheidung.
    """
    return {
        "type": "object",
        "properties": {
            "begruendung": {"type": "string"},
            "treffer": {"enum": list(candidates) + [None]},
        },
        "required": ["begruendung", "treffer"],
    }


@lru_cache(maxsize=4096)
def _judge(term: str, candidates: tuple) -> Optional[str]:
    """Fragt das LLM, welcher Kandidat (falls einer) dieselbe Entitaet wie 'term' ist."""
    return judge_verdict(term, candidates)[0]


@lru_cache(maxsize=4096)
def judge_verdict(term: str, candidates: tuple) -> tuple:
    """
    Wie _judge, aber mit Begruendung: (Treffer oder None, Begruendung).
    """
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    prompt = template.format(term=term, candidates="\n".join(f"- {c}" for c in candidates))
    response = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=False,
        format=judge_schema(candidates),
        options={"num_predict": 300, "temperature": 0},
    )
    # Abgeschnittene/kaputte Antwort = im Zweifel nicht zusammenfuehren
    # (gleiche Haltung wie der Prompt: "Im Zweifel: nicht dieselbe Entitaet")
    try:
        verdict = json.loads(response["message"]["content"])
        answer, reason = verdict.get("treffer"), verdict.get("begruendung") or ""
    except (json.JSONDecodeError, AttributeError):
        return None, "Antwort nicht lesbar"
    return (answer if answer in candidates else None), reason


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
    # Erst nach Schwellenwert filtern, DANACH auf MAX_JUDGE_CANDIDATES
    # begrenzen (nicht umgekehrt): bei einem grossen Graphen koennen viele
    # lexikalisch aehnliche, aber inhaltlich andere Begriffe (z.B.
    # "MS-Risikogene", "progrediente MS") den echten Treffer ("Multiple
    # Sklerose", nur 0.587 - keine Textueberlappung mit "MS") aus den
    # Top-N verdraengen, wenn man zuerst kappt und erst dann filtert.
    above_threshold = [k for score, k in scored if score >= CANDIDATE_THRESHOLD]
    candidates = tuple(above_threshold[:MAX_JUDGE_CANDIDATES])
    if not candidates:
        return None
    return _judge(term, candidates)


def similar_entities(names: list, known_terms: list, limit: int = 3,
                     threshold: float = SIMILAR_THRESHOLD) -> dict:
    """
    Fuer Entity-Linking in polygraph (vor der Extraktion): pro Name die bis
    zu 'limit' aehnlichsten bekannten Begriffe ueber 'threshold' - nur per
    Embedding, OHNE LLM-Richter, damit es schnell bleibt. Das sind nur
    Hinweise fuer den Extraktions-Prompt ("im Graphen bereits als: ..."),
    das Extraktionsmodell entscheidet selbst, ob es dieselbe Sache ist; die
    eigentliche Zusammenfuehrung macht weiterhin find_match() beim Import.

    Steht ein Name schon (auch in anderer Gross-/Kleinschreibung) im Graphen,
    gibt es keine Hinweise: er ist bereits kanonisch, weitere aehnliche
    Begriffe ("Muskelzellen" -> "Muskeln") wuerden nur zu falschem
    Umbenennen verleiten.
    """
    if not known_terms:
        return {name: [] for name in names}
    lowered = {k.lower().strip() for k in known_terms}
    result = {}
    for name in names:
        if name.lower().strip() in lowered:
            result[name] = []
            continue
        scored = _top_matches(_embed(name), known_terms)
        result[name] = [
            k for score, k in scored
            if score >= threshold and k != name
        ][:limit]
    return result


def normalize_triple(triple: dict, known_entities: list, known_relations: list) -> dict:
    """
    Ersetzt subject/object/relation im Tripel durch den kanonischen,
    bereits bekannten Begriff, falls das LLM sie als identisch bestaetigt.
    Subjekt und Objekt werden vorher ins Englische uebersetzt, ebenso
    value, condition und evidence_level.
    Modifiziert eine Kopie, nicht das Original.
    """
    normalized = dict(triple)
    known = set(known_entities)
    for field in ("subject", "object"):
        # Knoten sind immer englisch (graph/translate.py): erst uebersetzen,
        # dann gegen die (englischen) bekannten Knoten abgleichen. Ein
        # exakt bekannter Name braucht keinen LLM-Aufruf.
        term = triple[field] if triple[field] in known else to_english(triple[field])
        normalized[field] = find_match(term, known_entities) or term
    for field in DETAIL_FIELDS:
        if isinstance(triple.get(field), str) and triple[field].strip():
            normalized[field] = detail_to_english(triple[field])
    normalized["relation"] = find_match(triple["relation"], known_relations) or triple["relation"]
    return normalized
