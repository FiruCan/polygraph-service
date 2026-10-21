"""
Tests fuer den Duplikat-Aufraeumer: graph/dedupe.py (Kandidaten + Richter-
Agent, Ollama gemockt) und GraphStore.merge_nodes().
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph import dedupe
from graph.store import GraphStore


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


# --- find_duplicates + Richter-Agent --------------------------------------

VECTORS = {
    "Rauchen": [1.0, 0.0, 0.0],
    "cigarette smoking": [0.9, 0.3, 0.0],      # ~0.95 zu Rauchen
    "Nichtrauchen": [0.8, 0.6, 0.0],            # ~0.8 zu Rauchen
    "MS": [0.0, 0.7, 0.7],
    "Krebs": [0.0, 0.0, -1.0],
}


def fake_embed(model, input):
    return {"embeddings": [VECTORS[n] for n in input]}


def tool_call(name, **arguments):
    return {"message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}


def urteil(treffer, reason="gleich"):
    return tool_call("urteil", begruendung=reason, treffer=treffer or "")


def text(content):
    return {"message": {"role": "assistant", "content": content}}


def json_verdict(treffer, reason="gleich"):
    return text(json.dumps({"begruendung": reason, "treffer": treffer}))


def graph_with(*names):
    st = GraphStore()
    for n in names:
        add(st, n, "r", "Krebs")
    return st.graph


def run(graph, *responses, **kwargs):
    """find_duplicates mit festen Antworten des Richters, der Reihe nach -> (Ergebnis, chat-Mock)."""
    with patch("graph.dedupe.ollama.embed", side_effect=fake_embed), \
         patch("graph.dedupe.ollama.chat", side_effect=list(responses)) as chat:
        return dedupe.find_duplicates(graph, **kwargs), chat


def test_is_abbreviation():
    assert dedupe.is_abbreviation("MS") and dedupe.is_abbreviation("IL-6") and dedupe.is_abbreviation("OPCs")
    assert not dedupe.is_abbreviation("Rauchen") and not dedupe.is_abbreviation("multiple Sklerose")


def test_find_duplicates_proposes_judged_match_once_per_pair():
    result, chat = run(graph_with("Rauchen", "cigarette smoking"), urteil("cigarette smoking", "Uebersetzung"))
    assert chat.call_count == 1            # Rauchen<->cigarette smoking nur einmal, nicht in beide Richtungen
    assert result["richter_aufrufe"] == 1 and result["llm_aufrufe"] == 1
    [p] = result["vorschlaege"]
    assert {p["behalten"], p["entfernen"]} == {"Rauchen", "cigarette smoking"}
    assert p["begruendung"] == "Uebersetzung"
    assert p["schritte"] == []
    # Uebersetzung steht nicht in den Namen: Vorschlag ja, Freigabe nein
    assert p["beleg"] is None and p["freigegeben"] is False


def test_keep_is_node_with_more_edges():
    st = GraphStore()
    add(st, "Rauchen", "r", "Krebs")
    add(st, "Rauchen", "r2", "Krebs")
    add(st, "cigarette smoking", "r", "Krebs")
    [p] = run(st.graph, urteil("cigarette smoking"))[0]["vorschlaege"]
    # Richter mappt Rauchen -> cigarette smoking, behalten wird trotzdem der Knoten mit mehr Kanten
    assert p["behalten"] == "Rauchen" and p["entfernen"] == "cigarette smoking"
    assert p["kanten"] == {"Rauchen": 2, "cigarette smoking": 1}


def test_judge_rejection_gives_no_proposal():
    result, _ = run(graph_with("Rauchen", "Nichtrauchen"), urteil(None, "Gegenteil"))
    assert result["vorschlaege"] == []


def test_below_threshold_skips_judge():
    result, chat = run(graph_with("Rauchen", "MS"))
    assert result["richter_aufrufe"] == 0
    chat.assert_not_called()


def test_abbreviation_uses_lower_threshold():
    VECTORS["MS-ish"] = [0.0, 1.0, 0.0]   # zu MS ~0.71: unter 0.75, aber ueber der Abkuerzungs-Schwelle
    try:
        _, chat = run(graph_with("MS", "MS-ish"), urteil(None))
        assert chat.call_count == 1
        assert "MS-ish" in chat.call_args.kwargs["messages"][0]["content"]
    finally:
        del VECTORS["MS-ish"]


def test_limit_caps_judge_calls():
    result, chat = run(graph_with("Rauchen", "cigarette smoking", "Nichtrauchen"), urteil(None), limit=1)
    assert result["richter_aufrufe"] == 1
    assert chat.call_count == 1


def test_agent_may_pick_node_found_by_search():
    # "Tabakkonsum" ist kein Kandidat (Embedding zu weit weg, Namen belegen nichts) - der Agent findet ihn per Suche
    VECTORS["Tabakkonsum"] = [-1.0, 0.0, 0.0]
    try:
        result, chat = run(graph_with("Rauchen", "cigarette smoking", "Tabakkonsum"),
                           tool_call("suche_knoten", begriff="Tabak"),
                           urteil("Tabakkonsum", "Synonym"))
    finally:
        del VECTORS["Tabakkonsum"]
    assert chat.call_count == result["llm_aufrufe"] == 2
    [p] = result["vorschlaege"]
    assert {p["behalten"], p["entfernen"]} == {"Rauchen", "Tabakkonsum"}
    assert p["schritte"] == ["suche_knoten(Tabak)"]
    assert p["freigegeben"] is False      # ein Synonym belegen die Namen nicht
    tool_message = chat.call_args.kwargs["messages"][-1]
    assert tool_message["role"] == "tool" and "- Tabakkonsum" in tool_message["content"]


def test_names_add_long_form_as_candidate():
    # Embedding sieht "multiple sclerosis" nicht neben "MS" - die Wortanfaenge schon
    VECTORS.update({"MS-ish": [0.0, 1.0, 0.0], "multiple sclerosis": [-1.0, 0.0, 0.0]})
    try:
        result, chat = run(graph_with("MS", "MS-ish", "multiple sclerosis"), urteil("multiple sclerosis", "Abkuerzung"))
    finally:
        del VECTORS["MS-ish"], VECTORS["multiple sclerosis"]
    assert "- multiple sclerosis" in chat.call_args.kwargs["messages"][0]["content"]
    [p] = result["vorschlaege"]
    assert p["beleg"] == "abkuerzung" and p["freigegeben"] is True and p["mehrdeutig"] == []


def test_long_form_is_kept_even_with_fewer_edges():
    st = GraphStore()
    add(st, "MS", "r", "Krebs")
    add(st, "MS", "r2", "Krebs")
    add(st, "multiple sclerosis", "r", "Krebs")
    VECTORS["multiple sclerosis"] = [-1.0, 0.0, 0.0]
    try:
        [p] = run(st.graph, urteil("multiple sclerosis"))[0]["vorschlaege"]
    finally:
        del VECTORS["multiple sclerosis"]
    assert p["behalten"] == "multiple sclerosis" and p["entfernen"] == "MS"
    assert p["kanten"] == {"multiple sclerosis": 1, "MS": 2}


@pytest.mark.parametrize("treffer, freigegeben, mehrdeutig", [
    ("multiple sclerosis", True, []),                      # teilt "Vitamin D" mit MS
    ("muscle strength", False, ["multiple sclerosis"]),    # Buchstaben passen auch, Nachbarn sprechen dagegen
])
def test_ambiguous_abbreviation_is_decided_by_neighbors(treffer, freigegeben, mehrdeutig):
    st = GraphStore()
    add(st, "MS", "r", "Vitamin D")
    add(st, "multiple sclerosis", "r", "Vitamin D")
    add(st, "muscle strength", "r", "training")
    VECTORS.update({"multiple sclerosis": [-1.0, 0.0, 0.0], "muscle strength": [0.0, -1.0, 0.0],
                    "Vitamin D": [0.0, 0.0, -1.0], "training": [-0.7, -0.7, 0.0]})
    try:
        [p] = run(st.graph, urteil(treffer))[0]["vorschlaege"]
    finally:
        for name in ("multiple sclerosis", "muscle strength", "Vitamin D", "training"):
            del VECTORS[name]
    assert p["freigegeben"] is freigegeben and p["mehrdeutig"] == mehrdeutig


def test_unseen_or_invented_match_is_rejected():
    # "MS" existiert, kam dem Agenten aber nie unter die Augen; "Tabakkonsum" gibt es gar nicht
    assert run(graph_with("Rauchen", "cigarette smoking", "MS"), urteil("MS"))[0]["vorschlaege"] == []
    assert run(graph_with("Rauchen", "cigarette smoking"), urteil("Tabakkonsum"))[0]["vorschlaege"] == []


def test_verdict_matches_seen_names_case_insensitively_but_never_itself():
    assert len(run(graph_with("Rauchen", "cigarette smoking"), urteil("Cigarette Smoking"))[0]["vorschlaege"]) == 1
    assert run(graph_with("Rauchen", "cigarette smoking"), urteil("Rauchen"))[0]["vorschlaege"] == []


def test_plain_text_answer_is_followed_by_forced_json_verdict():
    result, chat = run(graph_with("Rauchen", "cigarette smoking"),
                       text("Das ist dasselbe."), json_verdict("cigarette smoking", "Uebersetzung"))
    assert result["llm_aufrufe"] == 2
    assert result["vorschlaege"][0]["begruendung"] == "Uebersetzung"
    forced = chat.call_args.kwargs
    assert "tools" not in forced
    assert forced["format"]["properties"]["treffer"]["enum"] == ["cigarette smoking", None]


def test_tool_rounds_are_capped():
    responses = [tool_call("suche_knoten", begriff="rauch")] * dedupe.MAX_TOOL_ROUNDS + [json_verdict(None)]
    result, chat = run(graph_with("Rauchen", "cigarette smoking"), *responses)
    assert chat.call_count == result["llm_aufrufe"] == dedupe.MAX_TOOL_ROUNDS + 1
    assert "format" in chat.call_args.kwargs and "tools" not in chat.call_args.kwargs


def test_unreadable_forced_verdict_gives_no_proposal():
    result, _ = run(graph_with("Rauchen", "cigarette smoking"), text("hmm"), text("{kaputt"))
    assert result["vorschlaege"] == []


def test_pair_found_again_by_search_is_proposed_once():
    # Rauchen -> cigarette smoking (Kandidat); danach findet der Agent fuer
    # cigarette smoking (Kandidat: Nichtrauchen) per Suche wieder Rauchen
    result, chat = run(graph_with("Rauchen", "cigarette smoking", "Nichtrauchen"),
                       urteil("cigarette smoking"),
                       tool_call("suche_knoten", begriff="rauchen"), urteil("Rauchen"))
    assert chat.call_count == 3
    assert len(result["vorschlaege"]) == 1


@pytest.mark.parametrize("a, b, beleg", [
    # echte Faelle aus den Live-Tests (2026-10-19)
    ("viral infections", "viral infection", "schreibweise"),
    ("High Intensity Training (HIT)", "high-intensity training", "schreibweise"),
    ("Krafttraining", "Kraft-Training", "schreibweise"),
    ("MS", "multiple sclerosis", "abkuerzung"),
    ("MS patients", "multiple sclerosis patients", "abkuerzung"),
    ("BDNF", "Brain-Derived Neurotrophic Factor", "abkuerzung"),
    ("NLR", "neutrophil-to-lymphocyte ratio", "abkuerzung"),   # Fuellwort "to" fehlt in der Abkuerzung
    ("OLCs", "oligodendrocyte lineage cells", "abkuerzung"),   # Mehrzahl
    ("TGF\u2010\u03b2", "transforming growth factor-beta", "abkuerzung"),
    ("EBV infection", "Epstein-Barr virus infections", "abkuerzung"),
    ("IgE", "immunoglobulin E", "abkuerzung"),                 # Kleinbuchstabe aus demselben Wort
    ("RRMS", "relapsing-remitting MS (RRMS)", "abkuerzung"),   # Abkuerzung in der Langform zaehlt ganz
    ("MWF", "myelin water fraction (MWF)", "abkuerzung"),      # Abkuerzung in Klammern am Ende
    ("DHA", "docosahexaenoic acid (DHA)", "abkuerzung"),
    ("MBI", "Mindfulness-based interventions (MBIs)", "abkuerzung"),
    ("MTR", "magnetization transfer ratio", "abkuerzung"),
    ("MBI", "BMI", None),                                      # zwei verschiedene Abkuerzungen
    ("MBI", "MS brain", None),
    ("MTR", "methotrexate", None),                             # Buchstaben nicht an Wortanfaengen
    ("MS", "Masitinib", None),
    ("CVD", "cardiovascular diseases", None),                  # V ist kein Wortanfang - lieber verpasst als falsch
    ("MS", "MS symptoms", None),                               # die Abkuerzung selbst ist keine Langform
    ("CNS", "chronic stress", None),
    ("IgE", "Inflammatory Gene Expression", None),
    ("ATP", "acceptance of the pathology", None),              # Fuellwoerter tragen nichts bei
    ("PLP", "rat monoclonal antibody against rat monoclonal anti-myelin proteolipid protein (PLP) antibody", None),
    ("Stress", "psychological stress", None),                  # ein Wort mehr
    ("EBV infection", "EBV", None),
    ("relapsing MS", "relapsing-remitting MS (RRMS)", None),
    ("Fatigue", "exhaustion", None),                           # Synonym ohne Beleg im Namen
    ("IL-6", "IL-8", None),
    ("type 1 diabetes", "type 2 diabetes", None),
    ("A2B5", "A2B5+ OPCs", None),
    ("HLA-A*02", "H2-aa", None),
])
def test_evidence_only_from_names(a, b, beleg):
    assert dedupe.evidence(a, b) == beleg
    assert dedupe.evidence(b, a) == beleg


def test_unproven_verdict_is_proposed_but_not_approved():
    VECTORS.update({"MBI": [0.0, 1.0, 0.1], "BMI": [0.0, 1.0, 0.0]})
    try:
        [p] = run(graph_with("MBI", "BMI"), urteil("BMI", "Tippfehler"))[0]["vorschlaege"]
    finally:
        del VECTORS["MBI"], VECTORS["BMI"]
    assert p["beleg"] is None and p["freigegeben"] is False


def test_search_lists_shortest_names_first():
    graph = graph_with("multiple sclerosis relapses", "multiple sclerosis", "Benign Multiple Sclerosis")
    _, hits = dedupe._tool_search(graph, "Sclerosis")
    assert hits == ["multiple sclerosis", "Benign Multiple Sclerosis", "multiple sclerosis relapses"]


def test_search_ignores_hyphens_and_case():
    graph = graph_with("Brain-Derived Neurotrophic Factor", "TGF‐β")
    assert dedupe._tool_search(graph, "brain derived neurotrophic")[1] == ["Brain-Derived Neurotrophic Factor"]
    assert dedupe._tool_search(graph, "tgf-β")[1] == ["TGF‐β"]


def test_tools_handle_bad_calls():
    graph = graph_with("Rauchen")
    assert dedupe._run_tool(graph, "suche_knoten", {"begriff": "Tabak"}) == ("Kein Knoten enthaelt 'Tabak'.", [])
    assert "Fehlendes Argument" in dedupe._run_tool(graph, "suche_knoten", {})[0]
    assert "Unbekanntes Werkzeug" in dedupe._run_tool(graph, "loeschen", {"knoten": "Rauchen"})[0]
