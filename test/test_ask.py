"""
Unit-Tests fuer graph/ask.py. ollama.chat wird gemockt - kein Ollama-Server
noetig. Geprueft wird die Agenten-Schleife: Werkzeugaufrufe, fortlaufende
Beleg-Nummern, Rundenlimit und was im API-Dict landet.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import ask as ask_mod
from graph.store import GraphStore


@pytest.fixture
def graph():
    store = GraphStore()
    for s, r, o, c in [
        ("Krafttraining", "reduces_risk_of", "Herz-Kreislauf-Erkrankungen", 0.9),
        ("Muskeln", "secretes", "Myokine", 0.8),
        ("Myokine", "reduces", "Entzuendungen", 0.7),
        ("Bewegung", "improves", "kognitive Leistungsfaehigkeit", 0.6),
    ]:
        store.add_triple({"subject": s, "subject_type": "x", "relation": r,
                          "object": o, "object_type": "y", "confidence": c})
    return store.graph


def tool_call(name, **args):
    return {"message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": name, "arguments": args}}]}}


def final(text):
    return {"message": {"role": "assistant", "content": text}}


def run(graph, question, selected, replies):
    with patch.object(ask_mod, "select_nodes", return_value=selected), \
         patch.object(ask_mod, "explain_terms", return_value=[]), \
         patch.object(ask_mod.ollama, "chat", side_effect=replies) as chat:
        return ask_mod.ask(graph, question), chat


def test_answers_directly_without_tools(graph):
    result, chat = run(graph, "Was senkt Herzrisiko?", ["Krafttraining"], [final("Krafttraining [1].")])
    assert chat.call_count == 1
    assert result["answer"] == "Krafttraining [1]."
    assert result["steps"] == []
    assert [t["n"] for t in result["triples"]] == [1]
    assert result["selected_nodes"] == ["Krafttraining"]


def test_tool_results_are_numbered_after_start_triples(graph):
    result, chat = run(graph, "Was machen Muskeln?", ["Krafttraining"], [
        tool_call("kanten_von", knoten="Myokine"),
        final("Myokine [2, 3]."),
    ])
    assert [(t["n"], t["subject"]) for t in result["triples"]] == [
        (1, "Krafttraining"), (2, "Muskeln"), (3, "Myokine")]
    assert result["steps"] == [{"tool": "kanten_von", "args": {"knoten": "Myokine"}, "new_triples": 2}]
    # Werkzeug-Ergebnis geht mit den neuen Nummern zurueck ans Modell
    tool_msg = chat.call_args.kwargs["messages"][-1]
    assert tool_msg["role"] == "tool" and "[2] Muskeln --secretes--> Myokine" in tool_msg["content"]
    assert "Myokine" in result["selected_nodes"]
    assert {e["source"] for e in result["graph"]["edges"]} == {"Krafttraining", "Muskeln", "Myokine"}


def test_known_edge_keeps_its_number(graph):
    result, chat = run(graph, "?", ["Krafttraining"], [
        tool_call("kanten_von", knoten="Krafttraining"), final("ok"),
    ])
    assert len(result["triples"]) == 1
    assert result["steps"][0]["new_triples"] == 0
    assert chat.call_args.kwargs["messages"][-1]["content"].startswith("[1] Krafttraining")


def test_search_and_path_tools(graph):
    result, chat = run(graph, "?", [], [
        tool_call("suche_knoten", begriff="myo"),
        tool_call("pfad", von="Muskeln", nach="Entzuendungen"),
        final("Muskeln senden Myokine [1], die Entzuendungen senken [2]."),
    ])
    search_msg = chat.call_args.kwargs["messages"][2]["content"]  # user, assistant, tool
    assert "- Myokine" in search_msg
    assert [t["subject"] for t in result["triples"]] == ["Muskeln", "Myokine"]
    assert set(result["selected_nodes"]) == {"Muskeln", "Entzuendungen"}


def test_unknown_node_gives_hint_instead_of_crash(graph):
    result, chat = run(graph, "?", [], [tool_call("kanten_von", knoten="Gibtsnicht"), final("Das steht nicht im Graphen.")])
    assert "existiert nicht" in chat.call_args.kwargs["messages"][-1]["content"]
    assert result["triples"] == [] and result["selected_nodes"] == []


def test_round_limit_forces_answer_without_tools(graph):
    loops = [tool_call("suche_knoten", begriff="x")] * ask_mod.MAX_TOOL_ROUNDS
    result, chat = run(graph, "?", [], loops + [final("Antwort")])
    assert chat.call_count == ask_mod.MAX_TOOL_ROUNDS + 1
    assert chat.call_args.kwargs["tools"] is None
    assert result["answer"] == "Antwort"


def test_no_start_nodes_still_runs_agent(graph):
    result, chat = run(graph, "Apple-Aktie?", [], [final("Das steht nicht im Graphen.")])
    assert "(keine - nutze die Werkzeuge)" in chat.call_args.kwargs["messages"][0]["content"]
    assert result["graph"] == {"nodes": [], "edges": []}


# --- Glossar ---

def glossary_reply(items):
    return {"message": {"role": "assistant", "content": json.dumps(items)}}


def all_edges(graph):
    return list(graph.edges(keys=True))


def test_glossary_candidates_only_terms_in_answer_with_type(graph):
    answer = "Muskeln schuetten Myokine aus [2], die Entzuendungen senken [3]."
    candidates = ask_mod.glossary_candidates(graph, answer, all_edges(graph))
    assert dict(candidates) == {"Muskeln": "x", "Myokine": "x", "Entzuendungen": "y"}


def test_explain_terms_keeps_known_and_drops_guesses(graph):
    answer = "Muskeln schuetten Myokine aus [2], die Entzuendungen senken [3]."
    reply = glossary_reply([
        {"begriff": "Myokine", "bekannt": True, "erklaerung": "Botenstoffe aus Muskelzellen."},
        {"begriff": "Entzuendungen", "bekannt": False, "erklaerung": "geraten"},
        {"begriff": "Myokine", "bekannt": True, "erklaerung": "doppelt"},
        {"begriff": "Erfunden", "bekannt": True, "erklaerung": "nicht in der Liste"},
    ])
    with patch.object(ask_mod.ollama, "chat", return_value=reply) as chat:
        glossary = ask_mod.explain_terms(graph, answer, all_edges(graph))
    assert glossary == [
        {"term": "Myokine", "type": "x", "explanation": "Botenstoffe aus Muskelzellen."},
        {"term": "Entzuendungen", "type": "y", "explanation": None},
    ]
    schema = chat.call_args.kwargs["format"]
    assert set(schema["items"]["properties"]["begriff"]["enum"]) == {"Muskeln", "Myokine", "Entzuendungen"}


def test_explain_terms_without_candidates_skips_llm(graph):
    with patch.object(ask_mod.ollama, "chat") as chat:
        assert ask_mod.explain_terms(graph, "Das steht nicht im Graphen.", all_edges(graph)) == []
    chat.assert_not_called()


def test_explain_terms_failure_gives_empty_glossary(graph):
    with patch.object(ask_mod.ollama, "chat", side_effect=RuntimeError("down")):
        assert ask_mod.explain_terms(graph, "Myokine [2].", all_edges(graph)) == []


def test_ask_returns_glossary(graph):
    with patch.object(ask_mod, "select_nodes", return_value=["Muskeln"]), \
         patch.object(ask_mod.ollama, "chat", side_effect=[
             final("Muskeln schuetten Myokine aus [1]."),
             glossary_reply([{"begriff": "Myokine", "bekannt": True, "erklaerung": "Botenstoffe."}]),
         ]):
        result = ask_mod.ask(graph, "Was machen Muskeln?")
    assert result["glossary"] == [{"term": "Myokine", "type": "x", "explanation": "Botenstoffe."}]


# --- ausfuehrliche Erklaerung ---

def test_explain_term_uses_context_but_no_triples(graph):
    reply = {"message": {"role": "assistant", "content": json.dumps(
        {"bekannt": True, "erklaerung": "  LINGO-1 ist ein Protein ...  "})}}
    with patch.object(ask_mod.ollama, "chat", return_value=reply) as chat:
        result = ask_mod.explain_term("LINGO-1", "Was hemmt Remyelinisierung?", "LINGO-1 hemmt sie [2].", "gene")
    assert result == {"term": "LINGO-1", "explanation": "LINGO-1 ist ein Protein ...", "known": True,
                      "used_sources": False}
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "Was hemmt Remyelinisierung?" in prompt and "Typ im Wissensgraphen: gene" in prompt
    assert "-->" not in prompt


def test_explain_term_passes_source_sentences(graph):
    reply = {"message": {"role": "assistant", "content": json.dumps({"bekannt": True, "erklaerung": "CN045 ..."})}}
    with patch.object(ask_mod.ollama, "chat", return_value=reply) as chat:
        result = ask_mod.explain_term("CN045", passages=["We identified a lead hit (CN045)."])
    assert result["used_sources"] is True
    assert "- We identified a lead hit (CN045)." in chat.call_args.kwargs["messages"][0]["content"]
