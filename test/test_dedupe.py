"""
Tests fuer den Duplikat-Aufraeumer: graph/dedupe.py (Kandidaten + Richter,
Ollama gemockt) und GraphStore.merge_nodes().
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import dedupe, normalize
from graph.store import GraphStore


@pytest.fixture(autouse=True)
def clear_caches():
    normalize.judge_verdict.cache_clear()
    yield
    normalize.judge_verdict.cache_clear()


def add(store, s, r, o, origin=None, **extra):
    store.add_triple({"subject": s, "relation": r, "object": o, "source": origin,
                      "subject_type": extra.pop("subject_type", None), **extra})


# --- merge_nodes ----------------------------------------------------------

@pytest.fixture
def store():
    st = GraphStore()
    add(st, "MS", "causes", "Fatigue", "A", subject_type="disease")
    add(st, "Vitamin D", "reduces_risk_of", "MS", "A")
    add(st, "multiple Sklerose", "causes", "Fatigue", "A", confidence=0.8)
    add(st, "multiple Sklerose", "causes", "Fatigue", "B")
    add(st, "MS", "abbreviation_of", "multiple Sklerose", "A")
    return st


def test_merge_moves_edges_and_removes_node(store):
    stats = store.merge_nodes("multiple Sklerose", "MS")
    g = store.graph
    assert "MS" not in g
    assert g.has_edge("Vitamin D", "multiple Sklerose")
    assert stats == {"moved": 1, "collapsed": 1, "dropped_self_loops": 1}


def test_merge_collapses_same_relation_and_source_and_fills_missing_fields(store):
    store.graph.edges["MS", "Fatigue", 0]["value"] = "haeufig"
    store.merge_nodes("multiple Sklerose", "MS")
    edges = store.graph["multiple Sklerose"]["Fatigue"]
    by_origin = {d["origin"]: d for d in edges.values()}
    assert set(by_origin) == {"A", "B"}          # A nicht verdoppelt, B bleibt eigene Belegstelle
    assert by_origin["A"]["confidence"] == 0.8   # bestehender Wert bleibt
    assert by_origin["A"]["value"] == "haeufig"  # fehlendes Feld ergaenzt


def test_merge_inherits_type_only_if_missing(store):
    store.merge_nodes("multiple Sklerose", "MS")
    assert store.graph.nodes["multiple Sklerose"]["type"] == "disease"
    st = GraphStore()
    add(st, "A", "r", "X", subject_type="t1")
    add(st, "B", "r", "Y", subject_type="t2")
    st.merge_nodes("A", "B")
    assert st.graph.nodes["A"]["type"] == "t1"


def test_merge_rejects_missing_or_same_node(store):
    with pytest.raises(KeyError):
        store.merge_nodes("MS", "gibtsnicht")
    with pytest.raises(ValueError):
        store.merge_nodes("MS", "MS")


def test_merged_graph_can_be_saved(store, tmp_path):
    store.merge_nodes("multiple Sklerose", "MS")
    store.save(str(tmp_path / "g.gml"))
    assert os.path.exists(tmp_path / "g.gml")


# --- find_duplicates ------------------------------------------------------

VECTORS = {
    "Rauchen": [1.0, 0.0, 0.0],
    "cigarette smoking": [0.9, 0.3, 0.0],      # ~0.95 zu Rauchen
    "Nichtrauchen": [0.8, 0.6, 0.0],            # ~0.8 zu Rauchen
    "MS": [0.0, 0.7, 0.7],
    "Krebs": [0.0, 0.0, -1.0],
}


def fake_embed(model, input):
    return {"embeddings": [VECTORS[n] for n in input]}


def verdict(treffer, reason="gleich"):
    return {"message": {"content": json.dumps({"begruendung": reason, "treffer": treffer})}}


def graph_with(*names):
    st = GraphStore()
    for n in names:
        add(st, n, "r", "Krebs")
    return st.graph


def test_is_abbreviation():
    assert dedupe.is_abbreviation("MS") and dedupe.is_abbreviation("IL-6") and dedupe.is_abbreviation("OPCs")
    assert not dedupe.is_abbreviation("Rauchen") and not dedupe.is_abbreviation("multiple Sklerose")


def test_find_duplicates_proposes_judged_match_once_per_pair():
    graph = graph_with("Rauchen", "cigarette smoking")
    with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=verdict("cigarette smoking", "Uebersetzung")) as chat:
        result = dedupe.find_duplicates(graph)
    assert chat.call_count == 1            # Rauchen<->cigarette smoking nur einmal, nicht in beide Richtungen
    assert result["richter_aufrufe"] == 1
    [p] = result["vorschlaege"]
    assert {p["behalten"], p["entfernen"]} == {"Rauchen", "cigarette smoking"}
    assert p["begruendung"] == "Uebersetzung"
    assert p["freigegeben"] is False


def test_keep_is_node_with_more_edges():
    st = GraphStore()
    add(st, "Rauchen", "r", "Krebs")
    add(st, "Rauchen", "r2", "Krebs")
    add(st, "cigarette smoking", "r", "Krebs")
    with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=verdict("cigarette smoking")):
        [p] = dedupe.find_duplicates(st.graph)["vorschlaege"]
    # Richter mappt Rauchen -> cigarette smoking, behalten wird trotzdem der Knoten mit mehr Kanten
    assert p["behalten"] == "Rauchen" and p["entfernen"] == "cigarette smoking"
    assert p["kanten"] == {"Rauchen": 2, "cigarette smoking": 1}


def test_judge_rejection_gives_no_proposal():
    graph = graph_with("Rauchen", "Nichtrauchen")
    with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=verdict(None, "Gegenteil")):
        assert dedupe.find_duplicates(graph)["vorschlaege"] == []


def test_below_threshold_skips_judge():
    graph = graph_with("Rauchen", "MS")
    with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat") as chat:
        assert dedupe.find_duplicates(graph)["richter_aufrufe"] == 0
    chat.assert_not_called()


def test_abbreviation_uses_lower_threshold():
    VECTORS["MS-ish"] = [0.0, 1.0, 0.0]   # zu MS ~0.71: unter 0.75, aber ueber der Abkuerzungs-Schwelle
    try:
        graph = graph_with("MS", "MS-ish")
        with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
             patch("graph.normalize.ollama.chat", return_value=verdict(None)) as chat:
            dedupe.find_duplicates(graph)
        assert chat.call_count == 1
        assert "MS-ish" in chat.call_args.kwargs["messages"][0]["content"]
    finally:
        del VECTORS["MS-ish"]


def test_limit_caps_judge_calls():
    graph = graph_with("Rauchen", "cigarette smoking", "Nichtrauchen")
    with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=verdict(None)) as chat:
        assert dedupe.find_duplicates(graph, limit=1)["richter_aufrufe"] == 1
    assert chat.call_count == 1
