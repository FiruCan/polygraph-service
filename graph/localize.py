"""
localize.py
-----------
Anzeige des Graphen in der Sprache des Lesers. Im Graphen selbst ist alles
englisch (graph/translate.py); die Oberflaeche zeigt Knotennamen, Typen,
Beziehungen und Kanten-Angaben aber in der gewaehlten Sprache ("Deutsch",
"Tuerkisch", ...). Nur fuer die Darstellung - an den Daten aendert sich nichts.

Ein LLM-Aufruf uebersetzt ein Paket von bis zu BATCH_SIZE Texten
(prompts/localize_labels.md). Jede Uebersetzung wird pro Sprache dauerhaft
gemerkt (data/labels/<Sprache>.json): der ganze Graph (~3.000 Knoten) dauert
beim ersten Mal lange, danach kommt alles sofort aus dem Cache.
"""

import json
import os
import re
import threading

import ollama

LOCALIZE_MODEL = "gemma4:26b"
BATCH_SIZE = 40
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "localize_labels.md")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "labels")
# Der Graph ist englisch - dafuer braucht es keine Uebersetzung.
SOURCE_LANGUAGES = {"englisch", "english"}

SCHEMA = {
    "type": "object",
    "properties": {
        "uebersetzungen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"original": {"type": "string"}, "uebersetzung": {"type": "string"}},
                "required": ["original", "uebersetzung"],
            },
        },
    },
    "required": ["uebersetzungen"],
}

_caches: dict = {}  # Sprache -> {original: Uebersetzung}
_lock = threading.Lock()


def _cache_path(language: str) -> str:
    # Sprachname aus dem Request -> sicherer Dateiname (kein "../")
    return os.path.join(CACHE_DIR, re.sub(r"[^\w-]", "_", language.strip().lower()) + ".json")


def _cache(language: str) -> dict:
    if language not in _caches:
        try:
            with open(_cache_path(language), "r", encoding="utf-8") as f:
                _caches[language] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _caches[language] = {}
    return _caches[language]


def _save(language: str):
    path = _cache_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_caches[language], f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _translate_batch(texts: list, language: str) -> dict:
    """
    -> {original: Uebersetzung} fuer ein Paket. Fehlt ein Text in der Antwort
    oder ist sie kaputt, bleibt er unveraendert (englisch).
    """
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    prompt = template.format(language=language, names="\n".join(f"- {t}" for t in texts))
    response = ollama.chat(
        model=LOCALIZE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=False,
        format=SCHEMA,
        options={"num_predict": 60 * len(texts) + 200, "temperature": 0},
    )
    try:
        items = json.loads(response["message"]["content"])["uebersetzungen"]
    except (json.JSONDecodeError, KeyError, TypeError):
        items = []
    wanted = set(texts)
    result = {t: t for t in texts}
    for item in items:
        original = item.get("original") if isinstance(item, dict) else None
        translated = (item.get("uebersetzung") or "").strip() if original else ""
        if original in wanted and translated:
            result[original] = translated
    return result


def localize(texts: list, language: str, cached_only: bool = False) -> dict:
    """
    -> {text: Uebersetzung in language}. cached_only: nur schon bekannte
    Uebersetzungen, ohne LLM-Aufruf - so holt die Oberflaeche fuer den ganzen
    Graphen erst alles Bekannte auf einmal und den Rest dann paketweise.
    """
    texts = list(dict.fromkeys(t for t in texts if isinstance(t, str) and t.strip()))
    if language.strip().lower() in SOURCE_LANGUAGES:
        return {t: t for t in texts}
    with _lock:
        cache = _cache(language)
        known = {t: cache[t] for t in texts if t in cache}
    if cached_only:
        return known
    todo = [t for t in texts if t not in known]
    for i in range(0, len(todo), BATCH_SIZE):
        batch = _translate_batch(todo[i:i + BATCH_SIZE], language)  # ohne Lock: dauert
        with _lock:
            _cache(language).update(batch)
            _save(language)
        known.update(batch)
    return known
