"""
Unit-Tests fuer graph/suggest.py (Beispielfragen). ollama.chat gemockt.
"""

import json
import os
import random
import sys
from unittest.mock import patch

import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph.suggest import SuggestionHistory, build_prompt, find_seeds, suggest_questions


def chain_graph():
    """
    Myokine -> Hippocampus -> Gedaechtnis -> Demenz, dazu ein Hub 'Muskeln';
    Krafttraining und Ausdauertraining wirken beide auf Muskeln (vergleich),
    zwei Kanten haben Details (detail).
    """
    g = nx.MultiDiGraph()
    for u, v, r, extra in [("Myokine", "Hippocampus", "regulates", {}),
                           ("Hippocampus", "Gedaechtnis", "supports", {}),
                           ("Gedaechtnis", "Demenz", "reduces_risk_of", {"evidence_level": "Kohortenstudie"}),
                           ("Muskeln", "Myokine", "secretes", {"condition": "bei Kontraktion"}),
                           ("Muskeln", "Stoffwechsel", "supports", {}),
                           ("Muskeln", "Blutzucker", "regulates", {}),
                           ("Krafttraining", "Muskeln", "supports", {}),
                           ("Ausdauertraining", "Muskeln", "supports", {}),
                           ("Ausdauertraining", "Stoffwechsel", "supports", {})]:
        g.add_edge(u, v, relation=r, **extra)
    return g


def answer(items):
    return {"message": {"content": json.dumps(items)}}


def seed_key(s):
    return (s["art"], tuple(sorted(s["knoten"])) if s["art"] != "detail" else tuple(s["knoten"]))


def test_empty_graph_no_seeds_no_llm():
    with patch("graph.suggest.ollama.chat") as chat:
        assert suggest_questions(nx.MultiDiGraph(), history=SuggestionHistory()) == []
    chat.assert_not_called()


def test_seeds_mix_kinds():
    seeds = find_seeds(chain_graph(), count=4, rng=random.Random(1))
    assert len(seeds) == 4
    assert len({s["art"] for s in seeds}) >= 3  # reihum verschiedene Arten
    for s in seeds:
        assert s["fakten"], s
        if s["art"] == "pfad":
            assert 2 <= len(s["fakten"]) <= 4  # 2-4 Schritte


def test_no_node_twice_within_one_round():
    for seed in range(10):
        seeds = find_seeds(chain_graph(), count=5, rng=random.Random(seed))
        knoten = [s["knoten"][0] for s in seeds if s["art"] == "knoten"]
        assert len(knoten) == len(set(knoten))


def test_detail_seed_carries_edge_details():
    found = []
    for seed in range(20):
        found += [s for s in find_seeds(chain_graph(), 4, random.Random(seed)) if s["art"] == "detail"]
    assert found
    for s in found:
        assert "[" in s["fakten"][0]  # Hauptfakt hat Bedingung/Wert/Evidenz
    assert any("Bedingung: bei Kontraktion" in s["fakten"][0] for s in found)


def test_vergleich_seed_shares_target():
    found = []
    for seed in range(20):
        found += [s for s in find_seeds(chain_graph(), 4, random.Random(seed)) if s["art"] == "vergleich"]
    assert found
    g = chain_graph()
    for s in found:
        a, b, target = s["knoten"]
        assert g.has_edge(a, target) and g.has_edge(b, target)


def test_facts_follow_existing_edges():
    g = chain_graph()
    for seed in range(10):
        for s in find_seeds(g, 5, random.Random(seed)):
            for fact in s["fakten"]:
                u, rest = fact.split(" --", 1)
                rel, v = rest.split("--> ", 1)
                v = v.split(" [")[0]
                assert g.has_edge(u, v), fact  # Fakt steht wirklich so im Graphen


def test_history_prevents_repeats_until_exhausted():
    g = chain_graph()
    history = SuggestionHistory()
    rng = random.Random(7)
    first = {seed_key(s) for s in find_seeds(g, 3, rng, history)}
    second = {seed_key(s) for s in find_seeds(g, 3, rng, history)}
    assert first and second
    assert not first & second


def test_history_starts_over_when_everything_used():
    g = chain_graph()
    history = SuggestionHistory()
    rng = random.Random(3)
    for _ in range(50):  # weit mehr Runden, als der kleine Graph Ausgangspunkte hat
        assert find_seeds(g, 3, rng, history), "nach dem Leeren des Verlaufs muss es weitergehen"


def test_suggest_uses_llm_wording():
    g = chain_graph()
    n = len(find_seeds(g, 3, random.Random(1)))
    items = [{"nr": i, "frage": f"Frage {i}?"} for i in range(1, n + 1)]
    with patch("graph.suggest.ollama.chat", return_value=answer(items)) as chat:
        result = suggest_questions(g, 3, random.Random(1), history=SuggestionHistory())
    assert [q["question"] for q in result] == [f"Frage {i}?" for i in range(1, n + 1)]
    assert chat.call_args.kwargs["format"]["items"]["required"] == ["nr", "frage"]


def test_suggest_falls_back_to_template_when_llm_fails():
    with patch("graph.suggest.ollama.chat", side_effect=RuntimeError("weg")):
        result = suggest_questions(chain_graph(), 4, random.Random(1), history=SuggestionHistory())
    assert result
    for q in result:
        k = q["nodes"]
        if q["type"] == "pfad":
            assert q["question"] == f"How are {k[0]} and {k[1]} connected?"
        elif q["type"] == "detail":
            assert q["question"] == f"Under which conditions is {k[0]} related to {k[1]}?"
        elif q["type"] == "vergleich":
            assert q["question"] == f"Do {k[0]} and {k[1]} affect {k[2]} in the same way?"
        else:
            assert q["question"] == f"What is known about {k[0]}?"


def test_suggest_fills_missing_items_from_template():
    with patch("graph.suggest.ollama.chat", return_value=answer([{"nr": 1, "frage": "Nur eine?"}])):
        result = suggest_questions(chain_graph(), 3, random.Random(1), history=SuggestionHistory())
    assert result[0]["question"] == "Nur eine?"
    assert all(q["question"] for q in result[1:])


def test_build_prompt_lists_seeds_with_facts():
    seeds = [{"art": "pfad", "knoten": ["Myokine", "Demenz"], "fakten": ["Myokine --regulates--> Hippocampus"]},
             {"art": "knoten", "knoten": ["Muskeln"], "fakten": ["Muskeln --secretes--> Myokine"]},
             {"art": "detail", "knoten": ["Muskeln", "Myokine"],
              "fakten": ["Muskeln --secretes--> Myokine [Bedingung: bei Kontraktion]"]},
             {"art": "vergleich", "knoten": ["Krafttraining", "Ausdauertraining", "Muskeln"],
              "fakten": ["Krafttraining --supports--> Muskeln"]}]
    prompt = build_prompt(seeds)
    assert "1. Art: pfad | von Myokine nach Demenz" in prompt
    assert "2. Art: knoten | Muskeln" in prompt
    assert "   - Muskeln --secretes--> Myokine" in prompt
    assert "3. Art: detail | Muskeln -> Myokine" in prompt
    assert "[Bedingung: bei Kontraktion]" in prompt
    assert "4. Art: vergleich | Krafttraining vs. Ausdauertraining, Ziel Muskeln" in prompt
