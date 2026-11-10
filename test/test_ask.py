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
         patch.object(ask_mod, "check_answer", return_value={"status": "geprueft", "saetze": []}), \
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


# --- Antwort-Pruefer (check_answer) ----------------------------------------

def checker_reply(*verdicts):
    return {"message": {"content": json.dumps([
        {"nr": i, "belege": b, "begruendung": f"Grund {i}", "urteil": u}
        for i, (u, b) in enumerate(verdicts, 1)])}}


def test_split_statements_keeps_text_and_marks_german_vermutung():
    answer = ("Krafttraining senkt das Herzrisiko um 15 Prozent [1]. Das gilt z.B. bei zwei Einheiten pro Woche [1].\n\n"
              "- Muskeln geben Myokine ab [2].\n"
              "Vermutung (nicht im Graphen belegt): Vielleicht hilft das auch dem Gehirn. Sicher ist das nicht.")
    st = ask_mod.split_statements(answer)
    assert [s["satz"] for s in st] == [
        "Krafttraining senkt das Herzrisiko um 15 Prozent [1].",
        "Das gilt z.B. bei zwei Einheiten pro Woche [1].",
        "Muskeln geben Myokine ab [2].",
        "Vielleicht hilft das auch dem Gehirn.",
        "Sicher ist das nicht.",
    ]
    assert [s["vermutung"] for s in st] == [False, False, False, True, True]
    assert all(s["satz"] in answer for s in st)


def test_cited_numbers():
    assert ask_mod.cited_numbers("A [3] und B [2, 5].") == [3, 2, 5]


def test_check_answer_sends_only_cited_triples_and_skips_vermutung(graph):
    edges = list(graph.edges(keys=True))
    answer = "Krafttraining senkt das Risiko [1]. Myokine heilen Krebs [3].\nVermutung (nicht im Graphen belegt): Vielleicht."
    with patch.object(ask_mod.ollama, "chat",
                      return_value=checker_reply(("gedeckt", [1]), ("nicht_gedeckt", [9]))) as chat:
        result = ask_mod.check_answer(graph, answer, edges, "Deutsch")
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "[1] Krafttraining" in prompt and "[3] Myokine" in prompt and "[2]" not in prompt
    assert "Vielleicht" not in prompt
    assert result["status"] == "geprueft"
    assert [(s["urteil"], s["belege"]) for s in result["saetze"]] == [
        ("gedeckt", [1]), ("nicht_gedeckt", []), ("vermutung", [])]   # 9 ist kein zitierter Beleg -> raus


def test_check_answer_llm_marks_vermutung_in_other_languages(graph):
    edges = list(graph.edges(keys=True))
    answer = "Strength training lowers the risk [1].\nAssumption (not proven in the graph): It may help the brain."
    with patch.object(ask_mod.ollama, "chat", return_value=checker_reply(
            ("gedeckt", [1]), ("vermutung", []))) as chat:
        result = ask_mod.check_answer(graph, answer, edges, "Englisch")
    assert "auf Englisch" in chat.call_args.kwargs["messages"][0]["content"]
    assert [s["vermutung"] for s in result["saetze"]] == [False, True]


@pytest.mark.parametrize("reply", [
    {"message": {"content": "kaputt"}},
    {"message": {"content": "[]"}},                                    # falsche Anzahl
    {"message": {"content": "[]"}, "done_reason": "length"},
])
def test_check_answer_failure_returns_unchecked(graph, reply):
    edges = list(graph.edges(keys=True))
    with patch.object(ask_mod.ollama, "chat", return_value=reply):
        result = ask_mod.check_answer(graph, "Krafttraining senkt das Risiko [1].", edges)
    assert result["status"] == "ungeprueft" and result["saetze"] == [] and result["fehler"]


def test_check_answer_without_checkable_sentences_skips_llm(graph):
    with patch.object(ask_mod.ollama, "chat") as chat:
        result = ask_mod.check_answer(graph, "Vermutung (nicht im Graphen belegt): Vielleicht.", [])
    chat.assert_not_called()
    assert result["status"] == "geprueft"


def test_ask_includes_pruefung(graph):
    with patch.object(ask_mod, "select_nodes", return_value=["Krafttraining"]), \
         patch.object(ask_mod, "explain_terms", return_value=[]), \
         patch.object(ask_mod.ollama, "chat", side_effect=[
             final("Krafttraining senkt das Risiko [1]."), checker_reply(("gedeckt", [1]))]):
        result = ask_mod.ask(graph, "Was senkt das Risiko?")
    assert result["pruefung"]["status"] == "geprueft"
    assert result["pruefung"]["saetze"][0]["urteil"] == "gedeckt"


@pytest.fixture
def hub():
    """Ein Knoten mit mehr Kanten, als ins Prompt passen - die gesuchte ist nicht die sicherste."""
    store = GraphStore()
    for i in range(150):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": f"Zahl {i}",
                          "object_type": "y", "confidence": 1.0})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": "return on equity",
                      "object_type": "y", "value": "38%", "confidence": 0.8})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": "Epstein",
                      "object_type": "y", "confidence": 0.8})
    return store.graph


def objects(edges):
    return [v for _, v, _ in edges]


def test_big_node_puts_edges_about_the_question_first(hub):
    with patch.object(ask_mod, "question_terms", return_value=["return on equity", "Firma"]) as terms:
        edges = ask_mod.collect_edges(hub, ["Firma"], "Wie hoch ist die Eigenkapitalrendite?")
    terms.assert_called_once()
    assert len(edges) == ask_mod.MAX_TRIPLES and objects(edges)[0] == "return on equity"
    assert "Zahl 0" in objects(edges)  # "Firma" steht an jeder Kante und zieht nichts nach vorn


def test_edges_about_the_question_leave_room_for_the_overview():
    store = GraphStore()
    for i in range(150):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": f"sicher {i}",
                          "object_type": "y", "confidence": 1.0})
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": f"eps {i}",
                          "object_type": "y", "confidence": 0.5})
    with patch.object(ask_mod, "question_terms", return_value=["eps"]):
        found = objects(ask_mod.collect_edges(store.graph, ["Firma"], "Gewinn?"))
    assert sum(o.startswith("eps") for o in found) == ask_mod.MAX_TRIPLES - ask_mod.OVERVIEW_TRIPLES
    assert sum(o.startswith("sicher") for o in found) == ask_mod.OVERVIEW_TRIPLES


def test_direct_edges_beat_the_same_term_two_steps_away():
    store = GraphStore()
    for i in range(120):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": f"Zahl {i}",
                          "object_type": "y", "confidence": 1.0})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "competes_with", "object": "Andere",
                      "object_type": "y", "confidence": 1.0})
    store.add_triple({"subject": "Andere", "subject_type": "x", "relation": "reports", "object": "eps von Andere",
                      "object_type": "y", "confidence": 1.0})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": "eps von Firma",
                      "object_type": "y", "confidence": 0.5})
    with patch.object(ask_mod, "question_terms", return_value=["eps"]):
        found = objects(ask_mod.collect_edges(store.graph, ["Firma"], "Gewinn?"))
    assert found[:2] == ["eps von Firma", "eps von Andere"]


def test_short_terms_match_whole_words_only(hub):
    with patch.object(ask_mod, "question_terms", return_value=["eps"]):
        assert "Epstein" not in objects(ask_mod.collect_edges(hub, ["Firma"], "Gewinn?"))
    assert ask_mod._term_pattern("transistor").search("next-generation transistors")


def test_no_terms_keep_the_order_by_confidence(hub):
    with patch.object(ask_mod, "question_terms", return_value=[]):
        edges = ask_mod.collect_edges(hub, ["Firma"], "Gewinn?")
    assert "return on equity" not in objects(edges) and len(edges) == ask_mod.MAX_TRIPLES


def test_small_graph_needs_no_terms(graph):
    with patch.object(ask_mod, "question_terms") as terms:
        assert len(ask_mod.collect_edges(graph, ["Muskeln"], "Was machen Muskeln?")) == 2
    terms.assert_not_called()


@pytest.mark.parametrize("reply, expected", [
    ('["return on equity", " ROE ", "", 3]', ["return on equity", "ROE"]),
    ('```json\n["ROE"]\n```', ["ROE"]),
    ("keine Ahnung", []),
    ('{"a": 1}', []),
])
def test_question_terms_parses_or_gives_nothing(reply, expected):
    with patch.object(ask_mod.ollama, "chat", return_value=final(reply)):
        assert ask_mod.question_terms("Frage?") == expected


def test_edge_tool_filters_by_term_and_says_when_cut(hub):
    evidence = ask_mod._Evidence(hub)
    text, _ = ask_mod._tool_edges(hub, evidence, "Firma", "return on equity")
    assert "38%" in text and "Zahl" not in text and len(evidence.edges) == 1
    text, nodes = ask_mod._tool_edges(hub, evidence, "Firma", "gibt es nicht")
    assert "enthaelt" in text and nodes == ["Firma"]
    text, _ = ask_mod._tool_edges(hub, evidence, "Firma")
    assert f"{ask_mod.MAX_TOOL_TRIPLES} von 152 Tripeln" in text


def test_split_statements_keeps_dates_whole():
    answer = "Der Termin ist am 12. November 2026 [1]. Der Wert stieg auf 20. Danach fiel er [2]."
    assert [s["satz"] for s in ask_mod.split_statements(answer)] == [
        "Der Termin ist am 12. November 2026 [1].", "Der Wert stieg auf 20.", "Danach fiel er [2]."]


def test_check_asks_for_exactly_one_verdict_per_sentence(graph):
    edges = all_edges(graph)
    with patch.object(ask_mod.ollama, "chat", return_value=checker_reply(("gedeckt", [1]), ("gedeckt", [1]))) as chat:
        ask_mod.check_answer(graph, "Eins [1]. Zwei [1].", edges)
    schema = chat.call_args.kwargs["format"]
    assert schema["minItems"] == 2 and schema["maxItems"] == 2


def test_empty_answer_is_tried_again_without_thinking(graph):
    result, chat = run(graph, "Frage?", ["Muskeln"], [final(""), final("Jetzt mit Text [1].")])
    assert result["answer"] == "Jetzt mit Text [1]." and chat.call_count == 2
    assert chat.call_args.kwargs["think"] is False and chat.call_args.kwargs.get("tools") is None


def test_big_node_shows_each_statement_once():
    store = GraphStore()
    for i in range(10):
        store.add_triple({"subject": "Chef", "subject_type": "x", "relation": "employed_by", "object": "Firma",
                          "object_type": "y", "value": "CEO", "confidence": 1.0, "source": f"quelle{i}"})
    for i in range(120):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": f"Zahl {i}",
                          "object_type": "y", "confidence": 0.9})
    edges = ask_mod.collect_edges(store.graph, ["Firma"])
    assert sum(u == "Chef" for u, _, _ in edges) == 1 and len(edges) == ask_mod.MAX_TRIPLES


def test_equal_edges_show_the_newest_first():
    store = GraphStore()
    for i in range(101):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": f"alt {i}",
                          "object_type": "y", "as_of": "2024", "confidence": 1.0})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": "neu",
                      "object_type": "y", "as_of": "July 26, 2026", "confidence": 1.0})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": "aus neuer Quelle",
                      "object_type": "y", "published": "2026-08-13", "confidence": 1.0})
    assert objects(ask_mod.collect_edges(store.graph, ["Firma"]))[:2] == ["aus neuer Quelle", "neu"]


def test_triple_shows_when_the_source_was_published():
    store = GraphStore()
    store.add_triple({"subject": "A", "subject_type": "x", "relation": "r", "object": "B", "object_type": "y",
                      "published": "2026-08-13", "confidence": 0.9})
    edge = next(iter(store.graph.edges(keys=True)))
    assert "published: 2026-08-13" in ask_mod.format_triple(1, store.graph, edge)
    assert ask_mod.triple_dict(store.graph, edge)["published"] == "2026-08-13"
    assert ask_mod.triple_dict(store.graph, edge)["stand"] == "2026-08-13"


def test_question_terms_get_the_domain_notes():
    with patch.object(ask_mod.ollama, "chat", return_value=final('["EPS"]')) as chat:
        ask_mod.question_terms("Frage?", "\n\nHINWEISE ZUM FACHGEBIET:\n- consensus")
    assert "- consensus" in chat.call_args.kwargs["messages"][0]["content"]
    with patch.object(ask_mod.ollama, "chat", return_value=final('["EPS"]')) as chat:
        ask_mod.question_terms("Frage?")
    assert "{domain_notes}" not in chat.call_args.kwargs["messages"][0]["content"]


def test_estimate_two_steps_away_comes_in_with_its_terms():
    """Frage nach Erwartungen: die Schaetzung haengt an "Zacks Consensus Estimate", zwei Schritte
    von der Firma entfernt, und viele direkte EPS-Kanten verdraengten sie, solange "estimate" fehlte."""
    store = GraphStore()
    store.graph.graph["profile"] = "finance"
    for i in range(150):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports",
                          "object": "earnings per share", "object_type": "y", "value": f"{i}.00",
                          "as_of": f"quarter {i}", "confidence": 1.0, "source": f"q{i}"})
    store.add_triple({"subject": "Zacks Consensus Estimate", "subject_type": "x", "relation": "forecasts",
                      "object": "earnings per share", "object_type": "y", "value": "$3.38",
                      "as_of": "third quarter fiscal year 2026", "confidence": 0.9})
    with patch.object(ask_mod, "question_terms", return_value=["earnings per share"]):
        assert "$3.38" not in [store.graph.edges[e].get("value")
                               for e in ask_mod.collect_edges(store.graph, ["Firma"], "Erwartungen?")]
    with patch.object(ask_mod, "question_terms", return_value=["earnings per share", "estimate", "consensus"]) as terms:
        found = [store.graph.edges[e].get("value") for e in ask_mod.collect_edges(store.graph, ["Firma"], "Erwartungen?")]
    assert "$3.38" in found and "consensus" in terms.call_args.args[1]


def test_check_sees_the_question_for_numbers_it_names(graph):
    edges = list(graph.edges(keys=True))
    with patch.object(ask_mod.ollama, "chat", return_value=checker_reply(("gedeckt", [1]))) as chat:
        ask_mod.check_answer(graph, "Krafttraining senkt das Risiko [1].", edges, question="Senkt es das Risiko um mehr als 17 Prozent?")
    assert "mehr als 17 Prozent?" in chat.call_args.kwargs["messages"][0]["content"]
    with patch.object(ask_mod.ollama, "chat", return_value=checker_reply(("gedeckt", [1]))) as chat:
        ask_mod.check_answer(graph, "Krafttraining senkt das Risiko [1].", edges)
    assert "{question}" not in chat.call_args.kwargs["messages"][0]["content"]


def test_ask_passes_the_question_to_the_check(graph):
    with patch.object(ask_mod, "select_nodes", return_value=["Muskeln"]), \
         patch.object(ask_mod, "explain_terms", return_value=[]), \
         patch.object(ask_mod, "check_answer", return_value={"status": "geprueft", "saetze": []}) as check, \
         patch.object(ask_mod.ollama, "chat", return_value=final("Muskeln bilden Myokine [1].")):
        ask_mod.ask(graph, "Was machen Muskeln?")
    assert check.call_args.args[-1] == "Was machen Muskeln?"


def test_question_terms_are_the_same_each_time():
    with patch.object(ask_mod.ollama, "chat", return_value=final('["EPS"]')) as chat:
        ask_mod.question_terms("Frage?")
    assert chat.call_args.kwargs["options"]["temperature"] == 0


def test_select_nodes_is_the_same_each_time(graph):
    with patch.object(ask_mod.ollama, "chat", return_value=final('["Muskeln"]')) as chat:
        assert ask_mod.select_nodes(graph, "Was machen Muskeln?") == ["Muskeln"]
    assert chat.call_args.kwargs["options"]["temperature"] == 0


def test_annual_value_named_as_twelve_months_comes_in_for_fiscal_years():
    """Der Jahreswert 2024 stand als "twelve months ended October 27, 2024" im Graphen und kam nie ins Prompt."""
    store = GraphStore()
    store.graph.graph["profile"] = "finance"
    for i in range(150):
        store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports",
                          "object": "earnings per share", "object_type": "y", "value": f"{i}.00",
                          "as_of": f"Q{i % 4 + 1} {2000 + i}", "confidence": 1.0, "source": f"q{i}"})
    store.add_triple({"subject": "Firma", "subject_type": "x", "relation": "reports", "object": "earnings per share",
                      "object_type": "y", "value": "$8.65", "as_of": "twelve months ended October 27, 2024",
                      "confidence": 0.9})
    with patch.object(ask_mod, "question_terms", return_value=["earnings per share", "fiscal year"]):
        found = [store.graph.edges[e].get("value") for e in ask_mod.collect_edges(store.graph, ["Firma"], "Jahre?")]
    assert found[0] == "$8.65"
