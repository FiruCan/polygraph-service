"""
normalize.py
------------
Normalisierung von Entitaets- und Relationsnamen, damit z.B. "IL-6" und
"Interleukin-6 (IL-6)" oder "Muskeln" und "Muskulatur" auf denselben Knoten
abgebildet werden - aber "Typ-I-Diabetes" und "Typ-II-Diabetes" nicht.

Zwei Stufen, ueber graph/llm.py (ohne llm.json komplett lokal ueber Ollama):
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
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Optional

import numpy as np

from domains import generic
from graph import llm
from graph.translate import detail_to_english, to_english

CANDIDATE_THRESHOLD = 0.55
# Hinweis-Schwelle fuer similar_entities(): bewusst niedrig, weil das
# Embedding Abkuerzungen schlecht erkennt ("IL6": IL-8 0.67, Interleukin-6
# 0.64). Ob ein Hinweis wirklich dieselbe Sache ist, entscheidet das
# Extraktionsmodell (Regel in polygraph/prompts/extract.md).
SIMILAR_THRESHOLD = 0.6
MAX_JUDGE_CANDIDATES = 20
EMBED_BATCH = 64
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "normalize_judge.md")

# Begriff -> Embedding, ohne Obergrenze: jeder Begriff wird nur einmal berechnet.
# Vorher lru_cache(4096) mit einem Aufruf pro Begriff - nach einem Neustart
# brauchte der erste Import so 140 s fuer 1.132 Begriffe (0,35 s je Aufruf,
# 50 Begriffe im Paket 0,5 s), und /entities/similar lief in den 30-s-Timeout
# von polygraph: die Extraktion lief dann still ohne Graph-Hinweise. Ab 4.096
# Begriffen haette der Cache bei jedem Import neu gerechnet. Ein Vektor (bge-m3)
# sind 4 KB, 10.000 Begriffe also rund 40 MB.
_vectors: dict = {}


def _embed_many(terms) -> None:
    """Berechnet die noch fehlenden Embeddings in Paketen von EMBED_BATCH."""
    todo = list(dict.fromkeys(t for t in terms if t not in _vectors))
    for i in range(0, len(todo), EMBED_BATCH):
        batch = todo[i:i + EMBED_BATCH]
        for term, vec in zip(batch, llm.embed(batch)["embeddings"]):
            _vectors[term] = np.array(vec, dtype=np.float32)


def warm_embeddings(terms) -> int:
    """Embeddings vorab berechnen (beim Serverstart), -> Anzahl neu berechneter Begriffe."""
    before = len(_vectors)
    _embed_many(terms)
    return len(_vectors) - before


def _embed(text: str) -> np.ndarray:
    _embed_many([text])
    return _vectors[text]


def _top_matches(term_vec: np.ndarray, known_terms: list) -> list:
    """
    Kosinus-Aehnlichkeit von term_vec gegen alle known_terms, vektorisiert:
    ein Matrix-Vektor-Produkt statt einer Python-Schleife mit sum()/sqrt()
    pro Begriffspaar. Gibt (score, term) absteigend sortiert zurueck.
    """
    _embed_many(known_terms)
    matrix = np.stack([_vectors[k] for k in known_terms])  # (N, D)
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
    response = llm.chat(
        "normalize", messages=[{"role": "user", "content": prompt}],
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


def _direct_match(term: str, known_terms: list) -> Optional[str]:
    """Bekannter Begriff in gleicher oder anderer Gross-/Kleinschreibung - ohne LLM."""
    if term in known_terms:
        return term
    lowered = {k.lower().strip(): k for k in known_terms}
    return lowered.get(term.lower().strip())


def _candidates(term: str, known_terms: list) -> tuple:
    """Bekannte Begriffe, ueber die der Richter fuer 'term' entscheiden soll (leer: keiner)."""
    if not known_terms:
        return ()
    _embed_many([term, *known_terms])  # neuer Begriff und unbekannte Knoten in einem Durchgang
    scored = _top_matches(_vectors[term], known_terms)
    # Erst nach Schwellenwert filtern, DANACH auf MAX_JUDGE_CANDIDATES
    # begrenzen (nicht umgekehrt): bei einem grossen Graphen koennen viele
    # lexikalisch aehnliche, aber inhaltlich andere Begriffe (z.B.
    # "MS-Risikogene", "progrediente MS") den echten Treffer ("Multiple
    # Sklerose", nur 0.587 - keine Textueberlappung mit "MS") aus den
    # Top-N verdraengen, wenn man zuerst kappt und erst dann filtert.
    above_threshold = [k for score, k in scored if score >= CANDIDATE_THRESHOLD]
    return tuple(above_threshold[:MAX_JUDGE_CANDIDATES])


def find_match(term: str, known_terms: list) -> Optional[str]:
    """
    Gibt den bekannten Begriff zurueck, der dieselbe Entitaet wie 'term'
    bezeichnet, oder None, falls 'term' neu ist.
    """
    direct = _direct_match(term, known_terms)
    if direct:
        return direct
    candidates = _candidates(term, known_terms)
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
    _embed_many([n for n in names if n.lower().strip() not in lowered] + list(known_terms))
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


def fixed_name(names, aliases: dict) -> Optional[str]:
    """
    Fester Knotenname des Profils (DomainProfile.aliases) fuer eine der
    Schreibweisen - auch wenn sie schon der feste Name ist -, sonst None.
    """
    targets = {name.casefold(): name for name in aliases.values()}
    for name in names:
        key = name.casefold()
        if key in aliases:
            return aliases[key]
        if key in targets:
            return targets[key]
    return None


def normalize_triple(triple: dict, known_entities: list, known_relations: list,
                     detail_fields: tuple = generic.PROFILE.detail_fields,
                     aliases: dict = None, fixed_relations=()) -> dict:
    """
    Ersetzt subject/object/relation im Tripel durch den kanonischen,
    bereits bekannten Begriff, falls das LLM sie als identisch bestaetigt.
    Subjekt und Objekt werden vorher ins Englische uebersetzt, ebenso die
    Kanten-Angaben in detail_fields (DomainProfile.detail_fields).
    Feste Namen (aliases) und feste Relationen (fixed_relations) des Profils
    gehen nicht durch den Richter: er hielt sonst "adjusted EPS" fuer
    "earnings per share" oder sells_stake_in fuer holds_stake_in, und beim
    Neuaufbau haengt das Ergebnis von der Reihenfolge der Importe ab.
    Modifiziert eine Kopie, nicht das Original.
    """
    normalized = dict(triple)
    known = set(known_entities)
    for field in ("subject", "object"):
        # Knoten sind immer englisch (graph/translate.py): erst uebersetzen,
        # dann gegen die (englischen) bekannten Knoten abgleichen. Ein
        # exakt bekannter Name braucht keinen LLM-Aufruf.
        term = triple[field] if triple[field] in known else to_english(triple[field])
        normalized[field] = (fixed_name((triple[field], term), aliases or {})
                             or find_match(term, known_entities) or term)
    for field in detail_fields:
        if isinstance(triple.get(field), str) and triple[field].strip():
            normalized[field] = detail_to_english(triple[field])
    relation = triple["relation"]
    normalized["relation"] = (relation if relation in fixed_relations
                              else find_match(relation, known_relations) or relation)
    return normalized


def prejudge(triples: list, known_entities: list, known_relations: list, aliases: dict = None,
             fixed_relations=(), workers: int = 1) -> int:
    """
    Stellt die Richter-Fragen eines Imports vorab, 'workers' gleichzeitig -
    normalize_triple findet die Urteile danach im Cache von judge_verdict.
    Die Begriffe entstehen wie in normalize_triple; das Ergebnis bleibt also
    dasselbe, nur schneller: im End-to-End-Test kosteten 27 Fragen
    nacheinander 54 s eines 230-s-Imports, der Server beantwortet 4 Fragen
    gleichzeitig in der Zeit von einer. Knoten, die erst ein frueheres Tripel
    desselben Imports anlegt, aendern die Kandidaten - diese Fragen stellt
    normalize_triple wie bisher selbst. -> Anzahl gestellter Fragen.
    """
    if workers <= 1:
        return 0
    known = set(known_entities)
    questions = set()
    for triple in triples:
        for field in ("subject", "object"):
            term = triple[field] if triple[field] in known else to_english(triple[field])
            if fixed_name((triple[field], term), aliases or {}) or _direct_match(term, known_entities):
                continue
            candidates = _candidates(term, known_entities)
            if candidates:
                questions.add((term, candidates))
        relation = triple["relation"]
        if relation not in fixed_relations and not _direct_match(relation, known_relations):
            candidates = _candidates(relation, known_relations)
            if candidates:
                questions.add((relation, candidates))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda q: judge_verdict(*q), questions))
    return len(questions)
