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
    normalize._vectors.clear()
    normalize._judge.cache_clear()
    normalize.judge_verdict.cache_clear()
    yield
    normalize._vectors.clear()
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
    return {"embeddings": [VECTORS[n] for n in input]}


def chat_answer(treffer):
    return {"message": {"content": json.dumps({"begruendung": "...", "treffer": treffer})}}


def test_find_match_exact_skips_llm():
    with patch("graph.llm.ollama.chat") as chat, patch("graph.llm.ollama.embed") as embed:
        assert find_match("Krebs", ["Krebs"]) == "Krebs"
    chat.assert_not_called()
    embed.assert_not_called()


def test_find_match_case_insensitive_skips_llm():
    with patch("graph.llm.ollama.chat") as chat:
        assert find_match(" krebs", ["Krebs"]) == "Krebs"
    chat.assert_not_called()


def test_find_match_empty_graph_returns_none():
    assert find_match("Krebs", []) is None


def test_find_match_asks_judge_only_with_candidates_above_threshold():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat", return_value=chat_answer("Interleukin-6")) as chat:
        result = find_match("IL-6", ["Interleukin-6", "IL-8", "Krebs"])
    assert result == "Interleukin-6"
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "- Interleukin-6" in prompt
    assert "- Krebs" not in prompt  # Kosinus 0 < CANDIDATE_THRESHOLD


def test_find_match_no_candidate_above_threshold_skips_llm():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat") as chat:
        assert find_match("IL-6", ["Krebs"]) is None
    chat.assert_not_called()


def test_judge_null_answer_means_new_entity():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat", return_value=chat_answer(None)):
        assert find_match("IL-6", ["Interleukin-6"]) is None


def test_judge_answer_not_in_candidates_is_rejected():
    # Das LLM darf keinen Begriff erfinden, der nicht zur Auswahl stand
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat", return_value=chat_answer("Interleukin 6 (IL-6)")):
        assert find_match("IL-6", ["Interleukin-6"]) is None


def test_judge_requests_enum_of_candidates_plus_null():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat", return_value=chat_answer("Interleukin-6")) as chat:
        find_match("IL-6", ["Interleukin-6", "IL-8"])
    schema = chat.call_args.kwargs["format"]
    assert schema["properties"]["treffer"]["enum"] == ["Interleukin-6", "IL-8", None]
    # Begruendung muss VOR dem Treffer stehen (Reihenfolge = Generierungsreihenfolge)
    assert list(schema["properties"]) == ["begruendung", "treffer"]


def test_judge_broken_json_means_no_merge():
    broken = {"message": {"content": '{"begruendung": "abgeschnitt'}}
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat", return_value=broken):
        assert find_match("IL-6", ["Interleukin-6"]) is None


def test_normalize_triple_maps_fields_and_keeps_rest():
    triple = {"subject": "IL-6", "relation": "reduces", "object": "Entzündungen", "value": "x"}
    matches = {"IL-6": "Interleukin-6", "Entzündungen": None, "reduces": "reduces"}
    with patch("graph.normalize.find_match", side_effect=lambda term, known: matches[term]):
        result = normalize_triple(triple, ["Interleukin-6"], ["reduces"])
    assert result == {"subject": "Interleukin-6", "relation": "reduces",
                      "object": "Entzündungen", "value": "x"}
    assert triple["subject"] == "IL-6"  # Original unveraendert


def test_top_matches_sorted_by_cosine():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed):
        scored = normalize._top_matches(np.array(VECTORS["IL-6"]), ["Krebs", "IL-8", "Interleukin-6"])
    assert [term for _, term in scored] == ["Interleukin-6", "IL-8", "Krebs"]


def test_similar_entities_returns_close_terms_without_llm():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat") as chat:
        result = normalize.similar_entities(["IL-6", "Krebs"], ["Interleukin-6", "IL-8", "Krebs"])
    chat.assert_not_called()
    assert result["IL-6"] == ["Interleukin-6", "IL-8"]  # nach Aehnlichkeit sortiert
    assert result["Krebs"] == []  # steht schon im Graphen -> keine Hinweise


def test_similar_entities_no_hints_for_known_name_any_case():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed):
        assert normalize.similar_entities(["krebs"], ["Krebs", "IL-6"]) == {"krebs": []}


def test_similar_entities_empty_graph():
    assert normalize.similar_entities(["IL-6"], []) == {"IL-6": []}


def test_profile_names_skip_the_judge():
    # Der Richter hielt "adjusted EPS" fuer "earnings per share" - der feste Name des Profils gewinnt
    aliases = {"adjusted eps": "adjusted earnings per share", "umsatz": "revenue"}
    judge = {"adjusted EPS": "earnings per share", "Umsatz": "sales", "ACME": "ACME"}
    with patch("graph.normalize.find_match", side_effect=lambda term, known: judge.get(term)) as match:
        eps = normalize_triple({"subject": "ACME", "relation": "reports", "object": "adjusted EPS"},
                               ["ACME", "earnings per share"], [], aliases=aliases)
        revenue = normalize_triple({"subject": "ACME", "relation": "reports", "object": "Umsatz"},
                                   ["ACME", "sales"], [], aliases=aliases)
        target = normalize_triple({"subject": "ACME", "relation": "reports", "object": "Revenue"},
                                  ["ACME", "sales"], [], aliases=aliases)
    assert eps["object"] == "adjusted earnings per share"
    assert revenue["object"] == "revenue"  # eine deutsche Schreibweise faengt der feste Name weiter ab
    assert target["object"] == "revenue"   # der feste Name selbst geht auch nicht zum Richter
    assert all(c.args[0] not in ("adjusted EPS", "Umsatz", "Revenue") for c in match.call_args_list)


def test_fixed_relations_skip_the_judge():
    triple = {"subject": "a", "relation": "sells_stake_in", "object": "b"}
    with patch("graph.normalize.find_match",
               side_effect=lambda term, known: "holds_stake_in" if term == "sells_stake_in" else term):
        fixed = normalize_triple(triple, ["a", "b"], ["holds_stake_in"],
                                 fixed_relations=frozenset({"sells_stake_in", "holds_stake_in"}))
        open_list = normalize_triple(triple, ["a", "b"], ["holds_stake_in"])
    assert fixed["relation"] == "sells_stake_in"
    assert open_list["relation"] == "holds_stake_in"  # ohne feste Liste entscheidet weiter der Richter


def test_fixed_name_matches_any_case_and_targets():
    aliases = {"eps": "earnings per share"}
    assert normalize.fixed_name(("EPS",), aliases) == "earnings per share"
    assert normalize.fixed_name(("Earnings per Share",), aliases) == "earnings per share"
    assert normalize.fixed_name(("Gewinn", "profit"), aliases) is None
    assert normalize.fixed_name(("EPS",), {}) is None


def test_embeddings_in_batches_and_only_once():
    # Kaltstart mit 130 bekannten Begriffen: 3 Pakete statt 130 Einzelaufrufe,
    # beim zweiten Mal kein Aufruf mehr (vorher 0,35 s je Begriff)
    known = [f"Begriff {i}" for i in range(130)]
    vectors = {k: [1.0, float(i), 0.0] for i, k in enumerate(known)}
    vectors["neu"] = [0.0, 0.0, 1.0]
    with patch("graph.llm.ollama.embed", side_effect=lambda model, input: {"embeddings": [vectors[n] for n in input]}) as embed:
        similar = normalize.similar_entities(["neu"], known)
        assert [len(c.kwargs["input"]) for c in embed.call_args_list] == [64, 64, 3]
        embed.reset_mock()
        normalize.similar_entities(["neu"], known)
        with patch("graph.llm.ollama.chat") as chat:
            assert find_match("neu", known) is None  # kein Kandidat ueber der Schwelle
        chat.assert_not_called()
    embed.assert_not_called()
    assert similar == {"neu": []}


def test_find_match_embeds_new_term_with_new_known_terms_in_one_call():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed) as embed, \
         patch("graph.llm.ollama.chat", return_value=chat_answer("Interleukin-6")):
        assert find_match("IL-6", ["Interleukin-6", "Krebs"]) == "Interleukin-6"
    assert embed.call_count == 1
    assert set(embed.call_args.kwargs["input"]) == {"IL-6", "Interleukin-6", "Krebs"}


def test_prejudge_asks_in_parallel_and_normalize_reuses_the_verdicts():
    with patch("graph.llm.ollama.embed", side_effect=fake_embed), \
         patch("graph.llm.ollama.chat", return_value=chat_answer("Interleukin-6")) as chat:
        asked = normalize.prejudge([{"subject": "IL-6", "relation": "increases_risk_of", "object": "Krebs"}],
                                   ["Interleukin-6", "Krebs"], ["increases_risk_of"], workers=4)
        assert asked == 1 and chat.call_count == 1  # Krebs und die Relation sind schon bekannt
        result = normalize_triple({"subject": "IL-6", "relation": "increases_risk_of", "object": "Krebs"},
                                  ["Interleukin-6", "Krebs"], ["increases_risk_of"])
    assert result["subject"] == "Interleukin-6"
    assert chat.call_count == 1  # Urteil aus dem Cache, kein zweiter Aufruf


def test_prejudge_with_one_worker_does_nothing():
    with patch("graph.llm.ollama.chat") as chat, patch("graph.llm.ollama.embed") as embed:
        assert normalize.prejudge([{"subject": "IL-6", "relation": "r", "object": "Krebs"}], ["Krebs"], ["r"]) == 0
    chat.assert_not_called(); embed.assert_not_called()
