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

from graph.suggest import build_prompt, find_seeds, suggest_questions


def chain_graph():
    """Myokine -> Hippocampus -> Gedaechtnis -> Demenz, dazu ein Hub 'Muskeln'."""
    g = nx.MultiDiGraph()
    for u, v, r in [("Myokine", "Hippocampus", "regulates"),
                    ("Hippocampus", "Gedaechtnis", "supports"),
                    ("Gedaechtnis", "Demenz", "reduces_risk_of"),
                    ("Muskeln", "Myokine", "secretes"),
                    ("Muskeln", "Stoffwechsel", "supports"),
                    ("Muskeln", "Blutzucker", "regulates"),
                    ("Krafttraining", "Muskeln", "supports")]:
        g.add_edge(u, v, relation=r)
    return g


def answer(items):
    return {"message": {"content": json.dumps(items)}}


def test_empty_graph_no_seeds_no_llm():
    with patch("graph.suggest.ollama.chat") as chat:
        assert suggest_questions(nx.MultiDiGraph()) == []
    chat.assert_not_called()


def test_seeds_mix_paths_and_nodes():
    seeds = find_seeds(chain_graph(), count=4, rng=random.Random(1))
    assert len(seeds) == 4
    kinds = [s["art"] for s in seeds]
    assert "knoten" in kinds
    for s in seeds:
        assert s["fakten"], s
        if s["art"] == "pfad":
            assert 2 <= len(s["fakten"]) <= 4  # 2-4 Schritte
    # kein Knoten kommt doppelt als Ausgangspunkt vor
    flat = [n for s in seeds if s["art"] == "knoten" for n in s["knoten"]]
    assert len(flat) == len(set(flat))


def test_path_facts_follow_existing_edges():
    seeds = find_seeds(chain_graph(), count=10, rng=random.Random(3))
    for s in seeds:
        for fact in s["fakten"]:
            u, rest = fact.split(" --")
            rel, v = rest.split("--> ")
            assert chain_graph().has_edge(u, v), fact  # Fakt steht wirklich so im Graphen


def test_suggest_uses_llm_wording():
    g = chain_graph()
    rng = random.Random(1)
    n = len(find_seeds(g, 3, random.Random(1)))
    items = [{"nr": i, "frage": f"Frage {i}?"} for i in range(1, n + 1)]
    with patch("graph.suggest.ollama.chat", return_value=answer(items)) as chat:
        result = suggest_questions(g, 3, rng)
    assert [q["question"] for q in result] == [f"Frage {i}?" for i in range(1, n + 1)]
    assert chat.call_args.kwargs["format"]["items"]["required"] == ["nr", "frage"]


def test_suggest_falls_back_to_template_when_llm_fails():
    with patch("graph.suggest.ollama.chat", side_effect=RuntimeError("weg")):
        result = suggest_questions(chain_graph(), 3, random.Random(1))
    assert result
    for q in result:
        if q["type"] == "pfad":
            assert q["question"] == f"Wie hängen {q['nodes'][0]} und {q['nodes'][1]} zusammen?"
        else:
            assert q["question"] == f"Was ist über {q['nodes'][0]} bekannt?"


def test_suggest_fills_missing_items_from_template():
    with patch("graph.suggest.ollama.chat", return_value=answer([{"nr": 1, "frage": "Nur eine?"}])):
        result = suggest_questions(chain_graph(), 3, random.Random(1))
    assert result[0]["question"] == "Nur eine?"
    assert all(q["question"] for q in result[1:])


def test_build_prompt_lists_seeds_with_facts():
    seeds = [{"art": "pfad", "knoten": ["Myokine", "Demenz"], "fakten": ["Myokine --regulates--> Hippocampus"]},
             {"art": "knoten", "knoten": ["Muskeln"], "fakten": ["Muskeln --secretes--> Myokine"]}]
    prompt = build_prompt(seeds)
    assert "1. Art: pfad | von Myokine nach Demenz" in prompt
    assert "2. Art: knoten | Muskeln" in prompt
    assert "   - Muskeln --secretes--> Myokine" in prompt
