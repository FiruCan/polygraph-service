"""
Unit-Tests fuer graph/normalize.py. ollama.embed und ollama.chat werden
gemockt - kein Ollama-Server noetig. Die echte Entscheidungsqualitaet des
LLM-Richters prueft test/test_normalize_judge_live.py gegen echtes Ollama.
"""

import json
import os
import sys
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import normalize
from graph.normalize import find_match, normalize_triple


@pytest.fixture(autouse=True)
def clear_caches():
    normalize._embed.cache_clear()
    normalize._judge.cache_clear()
    normalize.judge_verdict.cache_clear()
    yield
    normalize._embed.cache_clear()
    normalize._judge.cache_clear()
    normalize.judge_verdict.cache_clear()


# Feste Spielzeug-Vektoren: Aehnlichkeit laesst sich direkt ablesen
VECTORS = {
    "IL-6": [1.0, 0.0, 0.0],
    "Interleukin-6": [0.9, 0.1, 0.0],
    "IL-8": [0.7, 0.7, 0.0],
    "Krebs": [0.0, 0.0, 1.0],
}


def fake_embed(model, input):
    return {"embeddings": [VECTORS[input]]}


def chat_answer(treffer):
    return {"message": {"content": json.dumps({"begruendung": "...", "treffer": treffer})}}


def test_find_match_exact_skips_llm():
    with patch("graph.normalize.ollama.chat") as chat, patch("graph.normalize.ollama.embed") as embed:
        assert find_match("Krebs", ["Krebs"]) == "Krebs"
    chat.assert_not_called()
    embed.assert_not_called()


def test_find_match_case_insensitive_skips_llm():
    with patch("graph.normalize.ollama.chat") as chat:
        assert find_match(" krebs", ["Krebs"]) == "Krebs"
    chat.assert_not_called()


def test_find_match_empty_graph_returns_none():
    assert find_match("Krebs", []) is None


def test_find_match_asks_judge_only_with_candidates_above_threshold():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=chat_answer("Interleukin-6")) as chat:
        result = find_match("IL-6", ["Interleukin-6", "IL-8", "Krebs"])
    assert result == "Interleukin-6"
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "- Interleukin-6" in prompt
    assert "- Krebs" not in prompt  # Kosinus 0 < CANDIDATE_THRESHOLD


def test_find_match_no_candidate_above_threshold_skips_llm():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat") as chat:
        assert find_match("IL-6", ["Krebs"]) is None
    chat.assert_not_called()


def test_judge_null_answer_means_new_entity():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=chat_answer(None)):
        assert find_match("IL-6", ["Interleukin-6"]) is None


def test_judge_answer_not_in_candidates_is_rejected():
    # Das LLM darf keinen Begriff erfinden, der nicht zur Auswahl stand
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=chat_answer("Interleukin 6 (IL-6)")):
        assert find_match("IL-6", ["Interleukin-6"]) is None


def test_judge_requests_enum_of_candidates_plus_null():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=chat_answer("Interleukin-6")) as chat:
        find_match("IL-6", ["Interleukin-6", "IL-8"])
    schema = chat.call_args.kwargs["format"]
    assert schema["properties"]["treffer"]["enum"] == ["Interleukin-6", "IL-8", None]
    # Begruendung muss VOR dem Treffer stehen (Reihenfolge = Generierungsreihenfolge)
    assert list(schema["properties"]) == ["begruendung", "treffer"]


def test_judge_broken_json_means_no_merge():
    broken = {"message": {"content": '{"begruendung": "abgeschnitt'}}
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat", return_value=broken):
        assert find_match("IL-6", ["Interleukin-6"]) is None


def test_normalize_triple_maps_fields_and_keeps_rest():
    triple = {"subject": "IL-6", "relation": "reduces", "object": "Entzündungen", "value": "x"}
    matches = {"IL-6": "Interleukin-6", "Entzündungen": None, "reduces": "reduces"}
    with patch("graph.normalize.find_match", side_effect=lambda term, known: matches[term]), \
         patch("graph.normalize.to_english", side_effect=lambda n: n), \
         patch("graph.normalize.detail_to_english", side_effect=lambda t: t):
        result = normalize_triple(triple, ["Interleukin-6"], ["reduces"])
    assert result == {"subject": "Interleukin-6", "relation": "reduces",
                      "object": "Entzündungen", "value": "x"}
    assert triple["subject"] == "IL-6"  # Original unveraendert


def test_top_matches_sorted_by_cosine():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed):
        scored = normalize._top_matches(np.array(VECTORS["IL-6"]), ["Krebs", "IL-8", "Interleukin-6"])
    assert [term for _, term in scored] == ["Interleukin-6", "IL-8", "Krebs"]


def test_similar_entities_returns_close_terms_without_llm():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed), \
         patch("graph.normalize.ollama.chat") as chat:
        result = normalize.similar_entities(["IL-6", "Krebs"], ["Interleukin-6", "IL-8", "Krebs"])
    chat.assert_not_called()
    assert result["IL-6"] == ["Interleukin-6", "IL-8"]  # nach Aehnlichkeit sortiert
    assert result["Krebs"] == []  # steht schon im Graphen -> keine Hinweise


def test_similar_entities_no_hints_for_known_name_any_case():
    with patch("graph.normalize.ollama.embed", side_effect=fake_embed):
        assert normalize.similar_entities(["krebs"], ["Krebs", "IL-6"]) == {"krebs": []}


def test_similar_entities_empty_graph():
    assert normalize.similar_entities(["IL-6"], []) == {"IL-6": []}
