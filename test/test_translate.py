"""
Unit-Tests fuer graph/translate.py, die Uebersetzung beim Import
(normalize.normalize_triple) und translate_graph.py. ollama.chat und die
API-Aufrufe werden gemockt.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import translate_graph
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


def test_types_use_own_prompt():
    with patch("graph.translate.ollama.chat",
               return_value=answer([("Krankheiten", "diseases")])) as chat:
        assert translate.translate_types(["Krankheiten", "signaling_molecule"]) == {
            "Krankheiten": "diseases", "signaling_molecule": "signaling_molecule"}
    assert "TYPEN:" in chat.call_args.kwargs["messages"][0]["content"]


def test_prompt_names_topics_of_the_graph():
    with patch("graph.translate.ollama.chat", return_value=answer([("Bewegung", "motion")])) as chat:
        translate.translate_names(["Bewegung"], topics="physical_quantity, experiment")
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "physical_quantity, experiment" in prompt
    assert "biomedizin" not in prompt.lower() and "Gesundheitskontext" not in prompt
    with patch("graph.translate.ollama.chat", return_value=answer([])) as chat:
        translate.translate_details(["Faktor 1,8"])  # leerer Graph
    assert translate.NO_TOPICS in chat.call_args.kwargs["messages"][0]["content"]


# --- translate_graph.py ----------------------------------------------------

def test_renames_skip_case_only_changes_and_flag_merges():
    values = ["Krankheiten", "diseases", "Fatigue", "Müdigkeit"]
    translated = {"Krankheiten": "diseases", "diseases": "diseases", "Fatigue": "fatigue",
                  "Müdigkeit": "fatigue"}
    assert translate_graph._renames(values, translated) == [
        {"alt": "Krankheiten", "neu": "diseases", "zusammenfuehren": True, "freigegeben": True},
        {"alt": "Müdigkeit", "neu": "Fatigue", "zusammenfuehren": True, "freigegeben": True},
    ]


def test_plan_only_types(tmp_path, monkeypatch):
    monkeypatch.setattr(translate_graph, "REVIEW_PATH", str(tmp_path / "review.json"))
    graph = {"nodes": [{"id": "a", "type": "Krankheiten"}, {"id": "b", "type": "disease"},
                       {"id": "c", "type": None}], "edges": []}
    with patch("translate_graph.requests.get") as get, \
         patch("translate_graph.translate_names") as names, \
         patch("translate_graph.translate_types",
               side_effect=lambda types, progress=None: {t: {"Krankheiten": "diseases"}.get(t, t) for t in types}):
        get.return_value.json.return_value = graph
        translate_graph.plan("http://x", ["typen"])
    names.assert_not_called()
    with open(tmp_path / "review.json", encoding="utf-8") as f:
        assert json.load(f) == {"typen": [
            {"alt": "Krankheiten", "neu": "diseases", "zusammenfuehren": False, "freigegeben": True}]}


def test_apply_renames_only_approved_types(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "graph.gml").write_text("graph [ ]")
    review = {"typen": [
        {"alt": "Krankheiten", "neu": "diseases", "zusammenfuehren": False, "freigegeben": True},
        {"alt": "Gehirn", "neu": "brain", "zusammenfuehren": False, "freigegeben": False}]}
    (tmp_path / "review.json").write_text(json.dumps(review))
    monkeypatch.setattr(translate_graph, "HERE", str(tmp_path))
    monkeypatch.setattr(translate_graph, "REVIEW_PATH", str(tmp_path / "review.json"))
    monkeypatch.setattr(translate_graph, "GRAPH_PATH", str(tmp_path / "graph.gml"))
    with patch("translate_graph.requests.post") as post:
        post.return_value.json.return_value = {"changed": 3}
        translate_graph.apply("http://x")
    post.assert_called_once_with("http://x/vocabulary/rename", timeout=600,
                                 json={"kind": "type", "old": "Krankheiten", "new": "diseases"})
    assert len(list((tmp_path / "data").glob("graph.backup-*.gml"))) == 1
