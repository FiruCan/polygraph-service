"""
dedupe.py
---------
Duplikat-Aufraeumer: durchsucht den ganzen Graphen nach Knoten, die dieselbe
Entitaet bezeichnen, aber beim Import nicht zusammengefuehrt wurden (z.B.
"MS" und "multiple Sklerose", "cigarette smoking" und "Rauchen"). Die
Synonym-Zusammenfuehrung in normalize.py greift nur beim Import und haengt
von der Reihenfolge ab - was dort durchrutscht, findet erst dieser Lauf.

Nur Vorschlaege: zusammengefuehrt wird erst nach Freigabe durch einen
Menschen (polygraph/dedupe.py -> POST /nodes/merge).

Ablauf (wie beim Import, nur ueber alle Knoten):
1. Embeddings aller Knoten (bge-m3, in Paketen - ~75 s fuer 2.800 Knoten).
2. Pro Knoten die aehnlichsten anderen Knoten als Kandidaten. Bewusst
   strenger als beim Import (CANDIDATE_THRESHOLD 0.55): ueber alle
   Knotenpaare waeren das ~68.000 Paare, bei 0.75 und hoechstens 5
   Kandidaten ~980 Richter-Aufrufe (gemessen ~4.7 s pro Aufruf, also
   ~75 Min. - mehr als die 1.3 s beim Import, weil oft viele Kandidaten
   auf einmal geprueft werden). Abkuerzungen bekommen die
   Import-Schwelle und mehr Kandidaten, weil das Embedding sie schlecht
   erkennt: "MS" ~ "multiple Sklerose" nur 0.66, "MS symptoms" 0.75.
3. Der bestehende LLM-Richter (normalize.judge_verdict) entscheidet, ob
   einer der Kandidaten dieselbe Entitaet ist. Ein Paar wird nur einmal
   geprueft (A mit B, nicht danach noch B mit A).

Vorschlag: der Knoten mit mehr Kanten bleibt (er ist der etabliertere
Name), bei Gleichstand der vom Richter gewaehlte. Der Mensch kann
"behalten"/"entfernen" in der Review-Datei tauschen.
"""

import time
from typing import Callable, Optional

import numpy as np
import ollama

from graph.normalize import CANDIDATE_THRESHOLD, EMBED_MODEL, judge_verdict

DEDUPE_THRESHOLD = 0.75
MAX_CANDIDATES = 5
ABBREVIATION_THRESHOLD = CANDIDATE_THRESHOLD
ABBREVIATION_MAX_CANDIDATES = 20
EMBED_BATCH = 64


def is_abbreviation(name: str) -> bool:
    """Kurz, ein Wort, mind. zwei Grossbuchstaben: MS, IL-6, OPCs, BDNF."""
    return len(name) <= 8 and " " not in name and sum(c.isupper() for c in name) >= 2


def embed_all(names: list) -> np.ndarray:
    """Normierte Embeddings (N, D) - in Paketen statt einzeln, ~4x schneller."""
    vectors = []
    for i in range(0, len(names), EMBED_BATCH):
        vectors += ollama.embed(model=EMBED_MODEL, input=names[i:i + EMBED_BATCH])["embeddings"]
    matrix = np.array(vectors, dtype=np.float32)
    return matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)


def find_duplicates(graph, threshold: float = DEDUPE_THRESHOLD, limit: Optional[int] = None,
                    progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """
    -> {"vorschlaege": [...], "richter_aufrufe": n, "knoten": N, "dauer_s": s}.
    limit begrenzt die Richter-Aufrufe (fuer Probelaeufe); progress(i, N)
    wird pro Knoten aufgerufen.
    """
    started = time.time()
    names = [str(n) for n in graph.nodes]
    if len(names) < 2:
        return {"vorschlaege": [], "richter_aufrufe": 0, "knoten": len(names), "dauer_s": 0.0}
    matrix = embed_all(names)

    compared, proposals, calls = set(), [], 0
    for i, name in enumerate(names):
        if progress:
            progress(i, len(names))
        if limit is not None and calls >= limit:
            break
        abbreviation = is_abbreviation(name)
        min_score = ABBREVIATION_THRESHOLD if abbreviation else threshold
        max_candidates = ABBREVIATION_MAX_CANDIDATES if abbreviation else MAX_CANDIDATES

        # zeilenweise statt N x N-Matrix: Speicher bleibt O(N) auch bei grossen Graphen
        scores = matrix @ matrix[i]
        scores[i] = -1.0
        order = np.argsort(-scores)[:max_candidates]
        candidates = [j for j in order if scores[j] >= min_score
                      and frozenset((i, j)) not in compared]
        if not candidates:
            continue
        compared.update(frozenset((i, j)) for j in candidates)

        calls += 1
        match, reason = judge_verdict(name, tuple(names[j] for j in candidates))
        if match is None:
            continue
        j = names.index(match)
        proposals.append(_proposal(graph, name, match, reason, float(scores[j])))

    proposals.sort(key=lambda p: -p["aehnlichkeit"])
    return {"vorschlaege": proposals, "richter_aufrufe": calls, "knoten": len(names),
            "dauer_s": round(time.time() - started, 1)}


def _proposal(graph, term: str, match: str, reason: str, score: float) -> dict:
    degree = {n: graph.degree(n) for n in (term, match)}
    keep, remove = (term, match) if degree[term] > degree[match] else (match, term)
    return {
        "behalten": keep,
        "entfernen": remove,
        "begruendung": reason,
        "aehnlichkeit": round(score, 3),
        "kanten": {keep: degree[keep], remove: degree[remove]},
        "typen": {keep: graph.nodes[keep].get("type"), remove: graph.nodes[remove].get("type")},
        "freigegeben": False,
    }
