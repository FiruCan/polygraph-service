"""
translate.py
------------
Einheitliche Sprache fuer Knotennamen: alles Englisch. Die Tripel kommen
aus deutschen und englischen Texten (polygraph extrahiert "in der Sprache
des Textes"), ohne Uebersetzung stehen sonst "Multiple Sklerose" und
"multiple sclerosis" als zwei Knoten nebeneinander - die Synonym-Erkennung
in normalize.py findet solche Paare ueber Sprachgrenzen hinweg nur
unzuverlaessig.

Dasselbe gilt fuer die Angaben an den Kanten (value, condition,
evidence_level): "1,9 bis 3,3 Prozent" -> "1.9 to 3.3 percent",
"Metaanalyse" -> "meta-analysis". Alles im Graphen ist englisch - nur
Fragen und Antworten gibt es in der Sprache, die der Leser waehlt.

Ein LLM-Aufruf uebersetzt ein ganzes Paket auf einmal, Knotennamen
(prompts/translate_names.md) und Kanten-Angaben
(prompts/translate_details.md) mit je eigenem Prompt; schon Englisches,
Abkuerzungen und Eigennamen bleiben unveraendert. Jeder Text wird nur
einmal uebersetzt (Cache).

Genutzt beim Import (normalize.normalize_triple) und fuer die einmalige
Umstellung des Bestands (translate_graph.py -> POST /nodes/rename).
"""

import json
import os

import ollama

TRANSLATE_MODEL = "gemma4:26b"
BATCH_SIZE = 40
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")
PROMPTS = {"names": "translate_names.md", "details": "translate_details.md"}
# Kanten-Felder mit Freitext aus dem Quelltext (confidence ist eine Zahl)
DETAIL_FIELDS = ("value", "condition", "evidence_level")

_cache: dict = {}

SCHEMA = {
    "type": "object",
    "properties": {
        "uebersetzungen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"original": {"type": "string"}, "englisch": {"type": "string"}},
                "required": ["original", "englisch"],
            },
        },
    },
    "required": ["uebersetzungen"],
}


def _translate_batch(names: list, kind: str) -> dict:
    """
    -> {original: englisch} fuer ein Paket. Fehlt ein Name in der Antwort
    oder ist sie kaputt, bleibt er unveraendert - lieber ein deutscher
    Knoten als ein falsch zugeordneter.
    """
    with open(os.path.join(PROMPT_DIR, PROMPTS[kind]), "r", encoding="utf-8") as f:
        template = f.read()
    prompt = template.format(names="\n".join(f"- {n}" for n in names))
    response = ollama.chat(
        model=TRANSLATE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=False,
        format=SCHEMA,
        options={"num_predict": 60 * len(names) + 200, "temperature": 0},
    )
    try:
        items = json.loads(response["message"]["content"])["uebersetzungen"]
    except (json.JSONDecodeError, KeyError, TypeError):
        items = []
    wanted = set(names)
    result = {n: n for n in names}
    for item in items:
        original = item.get("original") if isinstance(item, dict) else None
        english = (item.get("englisch") or "").strip() if original else ""
        if original in wanted and english:
            result[original] = english
    return result


def translate_names(names: list, progress=None, kind: str = "names") -> dict:
    """
    -> {name: englisch} fuer alle names (unveraendert, wenn schon
    englisch). kind: "names" (Knoten) oder "details" (Kanten-Angaben).
    progress(fertig, gesamt) wird nach jedem Paket aufgerufen.
    """
    todo = list(dict.fromkeys(n for n in names if (kind, n) not in _cache))
    for i in range(0, len(todo), BATCH_SIZE):
        batch = _translate_batch(todo[i:i + BATCH_SIZE], kind)
        _cache.update({(kind, n): e for n, e in batch.items()})
        if progress:
            progress(min(i + BATCH_SIZE, len(todo)), len(todo))
    return {n: _cache[(kind, n)] for n in names}


def translate_details(texts: list, progress=None) -> dict:
    return translate_names(texts, progress, kind="details")


def to_english(name: str) -> str:
    return translate_names([name])[name]


def detail_to_english(text: str) -> str:
    return translate_details([text])[text]
