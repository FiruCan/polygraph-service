"""
Integrationstest: prueft den echten LLM-Richter (graph/normalize.py::_judge,
prompts/normalize_judge.md) gegen echtes Ollama mit Begriffspaaren bekannter
Soll-Antwort. Wird uebersprungen, wenn Ollama nicht laeuft.

Nach jeder Aenderung an normalize_judge.md oder JUDGE_MODEL laufen lassen:
    python3 -m pytest test/test_normalize_judge_live.py -v

Aufbau der Faelle: Synonyme, die zusammengefuehrt werden MUESSEN, und
Fehlerklassen, die getrennt bleiben MUESSEN. Die Kontrollgruppen stehen
bewusst NICHT als Beispiel im Prompt - wer nur den Prompt auf einzelne
Faelle zuschneidet, faellt dort auf. Gefunden 2026-10-08: "Glukose" wurde
mit "Blutzucker" zusammengefuehrt; eine erste, laengere Prompt-Regel
dagegen machte den Richter so vorsichtig, dass er echte Synonyme
("Entzündungsprozesse" = "Entzündungen") nicht mehr erkannte - deshalb
pruefen diese Tests beide Richtungen.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import normalize


def _ollama_available() -> bool:
    try:
        normalize.ollama.list()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ollama_available(), reason="Ollama laeuft nicht")

SAME = [
    ("IL-6", ["Interleukin-6", "IL-8", "Entzündungen"], "Interleukin-6"),
    ("MS", ["Multiple Sklerose", "Muskeln", "Rauchen"], "Multiple Sklerose"),
    ("Muskulatur", ["Muskeln", "Muskelzellen", "Muskelaufbau"], "Muskeln"),
    ("EZB", ["Europäische Zentralbank", "Leitzins"], "Europäische Zentralbank"),
    ("Entzündungsprozesse", ["Entzündungen", "Immunsystem"], "Entzündungen"),
    ("körperliche Bewegung", ["körperliche Aktivität", "Krafttraining"], "körperliche Aktivität"),
    ("Typ‑II‑Diabetes", ["Typ-II-Diabetes", "Typ-I-Diabetes"], "Typ-II-Diabetes"),
    ("Traubenzucker", ["Glukose", "Blutzucker"], "Glukose"),
    ("Blutglukose", ["Blutzucker", "Glukose"], "Blutzucker"),
]

DIFFERENT = [
    # beobachteter Fehler
    ("Glukose", ["Blutzucker", "Metabolite", "Fettsäuren"]),
    # Kontrollgruppe Stoff vs. Spiegel/Messwert (nicht im Prompt)
    ("Insulin", ["Insulinspiegel", "Blutzucker"]),
    ("Cholesterin", ["Cholesterinspiegel", "LDL"]),
    ("Vitamin D", ["Vitamin-D-Spiegel", "Vitamin-D-Mangel"]),
    ("Natrium", ["Blutdruck", "Salz"]),
    ("Eisen", ["Ferritin", "Hämoglobin"]),
    ("Kreatinin", ["Nierenfunktion", "Niere"]),
    ("Sauerstoff", ["Sauerstoffsättigung", "Atmung"]),
    ("Fruktose", ["Blutzucker", "Zucker"]),
    ("Leitzins", ["Zinserhöhung", "Europäische Zentralbank"]),
    # Klassen, die schon im Prompt stehen
    ("Typ-I-Diabetes", ["Typ-II-Diabetes"]),
    ("IL-8", ["Interleukin-6", "IL-15"]),
    ("Herz-Kreislauf-Erkrankungen", ["Erkrankungen"]),
    ("Muskelzellen", ["Muskeln"]),
    ("Skelettmuskel", ["Muskeln", "Muskelzellen"]),  # Unterbegriff
    # Kontextfall aus dem echten Graphen (2026-10-08): mit diesen 9 Kandidaten
    # waehlte der Richter ohne Begruendung den aehnlichsten ("Muskeln")
    ("Skelettmuskel", ["Muskeln", "Muskelaufbau", "Muskelprotein",
                       "Regeneration des Muskelgewebes", "Muskelzellen",
                       "Muskelkontraktionen", "gut ausgebildete Muskulatur",
                       "Mangel an funktioneller Muskelmasse", "körperliche Aktivität"]),
]


@pytest.fixture(autouse=True)
def fresh_judge_cache():
    normalize._judge.cache_clear()
    yield


@pytest.mark.parametrize("term,candidates,expected", SAME, ids=[c[0] for c in SAME])
def test_judge_merges_synonyms(term, candidates, expected):
    assert normalize._judge(term, tuple(candidates)) == expected


@pytest.mark.parametrize("term,candidates", DIFFERENT, ids=[f"{c[0]}-{len(c[1])}" for c in DIFFERENT])
def test_judge_keeps_different_concepts_apart(term, candidates):
    assert normalize._judge(term, tuple(candidates)) is None
