"""
Unit-Tests fuer graph/translate.py und die Uebersetzung beim Import
(normalize.normalize_triple). ollama.chat wird gemockt.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import normalize, translate
from graph.translate import translate_names


@pytest.fixture(autouse=True)
def clear_cache():
    translate._cache.clear()
    yield
    translate._cache.clear()


def answer(pairs):
    items = [{"original": o, "englisch": e} for o, e in pairs]
    return {"message": {"content": json.dumps({"uebersetzungen": items})}}


def test_translates_and_keeps_missing_names_unchanged():
    with patch("graph.translate.ollama.chat", return_value=answer([("Muskeln", "muscles")])):
        assert translate_names(["Muskeln", "IL-6"]) == {"Muskeln": "muscles", "IL-6": "IL-6"}


def test_ignores_names_not_asked_for_and_empty_translations():
    with patch("graph.translate.ollama.chat",
               return_value=answer([("erfunden", "made up"), ("Krebs", " ")])):
        assert translate_names(["Krebs"]) == {"Krebs": "Krebs"}


def test_broken_answer_keeps_names():
    broken = {"message": {"content": "{kaputt"}}
    with patch("graph.translate.ollama.chat", return_value=broken):
        assert translate_names(["Krebs"]) == {"Krebs": "Krebs"}


def test_batches_and_caches():
    names = [f"n{i}" for i in range(translate.BATCH_SIZE + 5)]
    with patch("graph.translate.ollama.chat", side_effect=lambda **kw: answer([])) as chat:
        progress = []
        translate_names(names, progress=lambda done, total: progress.append(done))
        translate_names(names)
    assert chat.call_count == 2  # zwei Pakete, zweiter Aufruf aus dem Cache
    assert progress == [translate.BATCH_SIZE, len(names)]
    prompt = chat.call_args_list[0].kwargs["messages"][0]["content"]
    assert "- n0" in prompt and f"- n{translate.BATCH_SIZE}" not in prompt


def test_normalize_triple_translates_new_names_before_matching():
    triple = {"subject": "Krafttraining", "relation": "reduces", "object": "cancer"}
    with patch("graph.normalize.to_english", side_effect=lambda n: {"Krafttraining": "strength training"}[n]) as tr, \
         patch("graph.normalize.find_match", side_effect=lambda term, known: term if term in known else None):
        result = normalize.normalize_triple(triple, ["cancer"], ["reduces"])
    assert result["subject"] == "strength training"
    assert result["object"] == "cancer"
    tr.assert_called_once_with("Krafttraining")  # bekannter Knoten braucht keine Uebersetzung


def test_details_use_own_prompt_and_cache():
    with patch("graph.translate.ollama.chat",
               return_value=answer([("Metaanalyse", "meta-analysis")])) as chat:
        assert translate.translate_details(["Metaanalyse"]) == {"Metaanalyse": "meta-analysis"}
        assert translate_names(["Metaanalyse"]) == {"Metaanalyse": "meta-analysis"}  # eigener Cache je Art
    assert chat.call_count == 2
    assert "ANGABEN:" in chat.call_args_list[0].kwargs["messages"][0]["content"]


def test_normalize_triple_translates_edge_details():
    triple = {"subject": "a", "relation": "r", "object": "b", "value": "20 Prozent",
              "condition": None, "confidence": 0.9}
    with patch("graph.normalize.detail_to_english", side_effect=lambda t: "20 percent"), \
         patch("graph.normalize.find_match", side_effect=lambda term, known: term):
        result = normalize.normalize_triple(triple, ["a", "b"], ["r"])
    assert result["value"] == "20 percent"
    assert result["condition"] is None and result["confidence"] == 0.9
