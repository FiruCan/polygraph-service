"""
Tests fuer die Domaenen-Profile (domains/): Register, Festlegen des Profils
(assign_profile), Speichern in der graph.gml und dass der Kern (to_json,
/ask, Fragevorschlaege, /edges/rewrite) die Kanten-Angaben des Profils nimmt
statt fester Felder - geprueft mit einem Test-Profil, das andere Angaben hat.
"""

import os
import sys
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as app_module
import domains
from domains import DomainProfile, Qualifier, assign_profile, get_profile, profile_of
from graph.ask import _distinct_statements, build_subgraph, format_triple, triple_dict
from graph.store import GraphStore
from graph.suggest import _node_facts

TEST_PROFILE = DomainProfile("test_markets", (
    Qualifier("value", "value", "Wert"),
    Qualifier("currency", "currency", "Waehrung", translate=False),
))


@pytest.fixture
def markets(monkeypatch):
    monkeypatch.setitem(domains.PROFILES, TEST_PROFILE.name, TEST_PROFILE)
    store = GraphStore()
    assign_profile(store.graph, TEST_PROFILE.name)
    store.add_triple({"subject": "ACME", "relation": "reports", "object": "revenue",
                      "value": "1.2 bn", "currency": "EUR", "evidence_level": "audited"})
    return store


# --- Register und Festlegen -------------------------------------------------

def test_generic_keeps_the_three_edge_fields():
    assert get_profile("generic").qualifier_fields == ("value", "condition", "evidence_level")


def test_medicine_has_own_fields_for_group_model_dose_duration():
    medicine = get_profile("medicine")
    fields = ("value", "population", "model", "dose", "duration", "condition", "evidence_level")
    assert medicine.qualifier_fields == fields
    assert medicine.detail_fields == fields  # alles Freitext, wird uebersetzt
    assert all(q.description for q in medicine.qualifiers)
    assert all(set(t) >= set(fields) for t in medicine.example_output)


def test_medicine_keeps_one_edge_per_group_of_one_source():
    store = GraphStore()
    assign_profile(store.graph, "medicine")
    base = {"subject": "Metformin", "relation": "reduces", "object": "HbA1c", "source": "a"}
    store.add_triple({**base, "population": "adults", "value": "1.1 %"})
    store.add_triple({**base, "population": "children", "value": "0.4 %"})
    store.add_triple({**base, "population": "adults", "value": "1.2 %"})  # selbe Aussage -> Update
    edges = store.graph.get_edge_data("Metformin", "HbA1c")
    assert sorted((e["population"], e["value"]) for e in edges.values()) == [("adults", "1.2 %"), ("children", "0.4 %")]


def test_medicine_notes_reach_check_prompt():
    from graph.ask import check_answer
    graph = nx.MultiDiGraph()
    assign_profile(graph, "medicine")
    graph.add_edge("clemastine", "remyelination", relation="promotes", model="mice")
    edges = list(graph.edges(keys=True))
    reply = {"message": {"content": '[{"nr": 1, "belege": [1], "begruendung": "ok", "urteil": "gedeckt"}]'}}
    with patch("graph.ask.ollama.chat", return_value=reply) as chat:
        check_answer(graph, "Clemastin foerdert die Remyelinisierung [1].", edges)
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert "Studienmodell (model)" in prompt
    assert "model: mice" in prompt


def test_unknown_profile_is_an_error():
    with pytest.raises(ValueError, match="Unbekanntes Profil"):
        get_profile("astrology")
    with pytest.raises(ValueError):
        assign_profile(nx.MultiDiGraph(), "astrology")


def test_new_empty_instance_gets_generic():
    graph = nx.MultiDiGraph()
    assert assign_profile(graph) is True
    assert graph.graph["profile"] == "generic"


def test_old_graph_without_request_stays_unassigned():
    graph = nx.MultiDiGraph()
    graph.add_edge("a", "b")
    assert assign_profile(graph) is False
    assert "profile" not in graph.graph
    assert profile_of(graph).name == "generic"


def test_old_graph_is_migrated_on_request():
    graph = nx.MultiDiGraph()
    graph.add_edge("a", "b")
    assert assign_profile(graph, "medicine") is True
    assert profile_of(graph).name == "medicine"


def test_stored_profile_is_fixed():
    graph = nx.MultiDiGraph()
    graph.graph["profile"] = "medicine"
    assert assign_profile(graph) is False
    assert assign_profile(graph, "medicine") is False
    with pytest.raises(ValueError, match="nicht gewechselt"):
        assign_profile(graph, "generic")
    assert graph.graph["profile"] == "medicine"


def test_profile_survives_save_and_load(tmp_path):
    store = GraphStore()
    assign_profile(store.graph, "medicine")
    store.add_triple({"subject": "a", "relation": "r", "object": "b"})
    store.save(str(tmp_path / "graph.gml"))
    loaded = GraphStore()
    loaded.load(str(tmp_path / "graph.gml"))
    assert profile_of(loaded.graph).name == "medicine"


# --- Der Kern folgt dem Profil ----------------------------------------------

def test_to_json_uses_profile_qualifiers(markets):
    edge = markets.to_json()["edges"][0]
    assert edge["currency"] == "EUR" and edge["value"] == "1.2 bn"
    assert "evidence_level" not in edge and "condition" not in edge


def test_ask_formats_use_profile_qualifiers(markets):
    edge = next(iter(markets.graph.edges(keys=True)))
    assert triple_dict(markets.graph, edge)["currency"] == "EUR"
    line = format_triple(1, markets.graph, edge)
    assert "currency: EUR" in line and "audited" not in line


def test_subgraph_keeps_profile(markets):
    sub = build_subgraph(markets.graph, list(markets.graph.edges(keys=True)))
    assert profile_of(sub).name == TEST_PROFILE.name


def test_suggest_facts_use_profile_labels(markets):
    import random
    facts = _node_facts(markets.graph, "ACME", random.Random(0))
    assert facts == ["ACME --reports--> revenue [Wert: 1.2 bn; Waehrung: EUR]"]


# --- API ----------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_PATH", str(tmp_path / "graph.gml"))
    monkeypatch.setattr(app_module, "store", GraphStore())
    monkeypatch.setitem(domains.PROFILES, TEST_PROFILE.name, TEST_PROFILE)
    with patch("app.normalize_triple", side_effect=lambda t, e, r, **kw: dict(t)) as normalize, \
         patch("app.translate_names"), patch("app.translate_details") as details, \
         patch("app.translate_types", side_effect=lambda types, topics="": {t: t for t in types}):
        client = TestClient(app_module.app)
        client.normalize, client.translate_details = normalize, details
        yield client


def test_get_profile_endpoint(client):
    data = client.get("/profile").json()
    assert data["name"] == "generic" and data["fixed"] is False
    assert [q["name"] for q in data["qualifiers"]] == ["value", "condition", "evidence_level"]
    assert "substance" in data["entity_types"]

    assign_profile(app_module.store.graph, "medicine")
    data = client.get("/profile").json()
    assert data["name"] == "medicine" and data["fixed"] is True


def test_import_translates_only_free_text_qualifiers(client):
    assign_profile(app_module.store.graph, TEST_PROFILE.name)
    client.post("/triples", json={"triples": [{"subject": "ACME", "relation": "reports", "object": "revenue",
                                               "value": "1,2 Mrd.", "currency": "EUR"}]})
    assert client.translate_details.call_args.args[0] == ["1,2 Mrd."]
    assert client.normalize.call_args.kwargs["detail_fields"] == ("value",)


def test_edges_rewrite_only_profile_fields(client):
    assign_profile(app_module.store.graph, TEST_PROFILE.name)
    r = client.post("/edges/rewrite", json={"rewrites": [
        {"field": "evidence_level", "old": "a", "new": "b"}]})
    assert r.status_code == 422
    assert "evidence_level" in r.json()["detail"]
    assert client.post("/edges/rewrite", json={"rewrites": [
        {"field": "value", "old": "a", "new": "b"}]}).json() == {"changed": 0}


# --- Finanz-Profil ----------------------------------------------------------

def test_finance_profile_has_date_and_currency():
    finance = get_profile("finance")
    assert finance.qualifier_fields == ("value", "condition", "evidence_level", "as_of", "currency", "negated")
    assert "currency" not in finance.detail_fields  # Waehrungscode wird nicht uebersetzt
    assert "as_of" in finance.detail_fields
    assert "company" in finance.entity_types and "acquires" in finance.relation_types
    assert all(q.description for q in finance.qualifiers)


def test_prompt_notes_only_for_profiles_that_have_them():
    assert get_profile("generic").notes("answer") == ""
    assert get_profile("generic").notes("check") == ""
    assert "model" in get_profile("medicine").notes("answer")
    assert get_profile("finance").notes("answer").startswith("\n\nHINWEISE ZUM FACHGEBIET:\n")
    assert get_profile("finance").notes("unbekannt") == ""


def test_finance_notes_reach_suggest_prompt():
    from graph.suggest import build_prompt
    seeds = [{"art": "knoten", "knoten": ["ACME"], "fakten": ["ACME --reports--> revenue"]}]
    assert "HINWEISE ZUM FACHGEBIET" not in build_prompt(seeds)
    assert "Stichtag" in build_prompt(seeds, domain_notes=get_profile("finance").notes("suggest"))


def test_finance_notes_reach_check_prompt():
    from graph.ask import check_answer
    graph = nx.MultiDiGraph()
    assign_profile(graph, "finance")
    graph.add_edge("ACME", "revenue", relation="reports", value="1.2 bn", as_of="Q3 2024", currency="EUR")
    edges = list(graph.edges(keys=True))
    reply = {"message": {"content": '[{"nr": 1, "belege": [1], "begruendung": "ok", "urteil": "gedeckt"}]'}}
    with patch("graph.ask.ollama.chat", return_value=reply) as chat:
        result = check_answer(graph, "ACME meldete einen Umsatz von 1,2 Milliarden Euro [1].", edges)
    prompt = chat.call_args.kwargs["messages"][0]["content"]
    assert result["status"] == "geprueft"
    assert "Stichtag (as of)" in prompt
    assert "as of: Q3 2024 | currency: EUR" in prompt


def test_finance_instance_reports_its_profile(client):
    assign_profile(app_module.store.graph, "finance")
    data = client.get("/profile").json()
    assert data["name"] == "finance"
    names = {q["name"]: q for q in data["qualifiers"]}
    assert names["currency"]["translate"] is False and names["as_of"]["label_de"] == "Stichtag"
    assert "Zeitpunkt" in names["as_of"]["description"]
    assert "Subjekt einer Kennzahl" in data["extract_notes"]


def test_extract_notes_only_for_profiles_that_have_them():
    assert "eigene Tripel" in get_profile("medicine").to_json()["extract_notes"]
    assert get_profile("generic").to_json()["extract_notes"] == ""
    assert "\"decreases\"" in get_profile("finance").to_json()["extract_notes"]


def test_finance_closes_relations_and_pins_the_currency_code():
    data = get_profile("finance").to_json()
    assert data["closed_relations"] is True
    patterns = {q["name"]: q["pattern"] for q in data["qualifiers"]}
    assert patterns["currency"] == "^[A-Z]{3}$" and patterns["value"] == ""
    assert get_profile("medicine").to_json()["closed_relations"] is False
    assert get_profile("generic").to_json()["closed_relations"] is False


def test_finance_closes_the_entity_types():
    data = get_profile("finance").to_json()
    assert data["closed_types"] is True
    assert {"technology", "organization", "index"} <= set(data["entity_types"])
    assert "\"organization\"" in data["extract_notes"]
    assert get_profile("medicine").to_json()["closed_types"] is False
    assert get_profile("generic").to_json()["closed_types"] is False



def test_finance_offers_news_and_science_variants():
    data = get_profile("finance").to_json()
    assert set(data["variants"]) == {"news", "science"} and data["description"]
    qualifiers = {q["name"] for q in data["qualifiers"]}
    for name, variant in data["variants"].items():
        assert variant["description"] and variant["extract_notes"]
        # das Beispiel haelt sich an die eigene feste Liste und hat alle Qualifier
        for t in variant["example_output"]:
            assert t["subject_type"] in variant["entity_types"], (name, t)
            assert t["object_type"] in variant["entity_types"], (name, t)
            assert t["relation"] in variant["relation_types"], (name, t)
            assert qualifiers <= set(t)
    # Bruecke zu den Finanzartikeln: Nachrichten koennen auf Kurse und Branchen wirken
    assert {"company", "index", "sector"} <= set(data["variants"]["news"]["entity_types"])
    assert get_profile("medicine").to_json()["variants"] == {}

def finance_store():
    store = GraphStore()
    assign_profile(store.graph, "finance")
    return store


def test_finance_keeps_one_edge_per_date_of_one_source():
    store = finance_store()
    base = {"subject": "VW", "relation": "reports", "object": "operating profit", "source": "q3.pdf"}
    store.add_triple({**base, "value": "2.9 bn", "as_of": "Q3 2024"})
    store.add_triple({**base, "value": "4.9 bn", "as_of": "Q3 2023"})
    store.add_triple({**base, "value": "3.0 bn", "as_of": "Q3 2024"})  # selbe Aussage -> Update
    edges = store.graph.get_edge_data("VW", "operating profit")
    assert sorted((e["as_of"], e["value"]) for e in edges.values()) == [("Q3 2023", "4.9 bn"), ("Q3 2024", "3.0 bn")]


def test_finance_keeps_one_edge_per_condition_of_one_source():
    store = finance_store()
    base = {"subject": "BMW", "relation": "reports", "object": "EBIT margin", "source": "q3.pdf", "as_of": "Q3 2024"}
    store.add_triple({**base, "value": "4.7 %"})
    store.add_triple({**base, "value": "2.3 %", "condition": "automotive segment"})
    assert len(store.graph.get_edge_data("BMW", "EBIT margin")) == 2


def test_medicine_still_updates_same_relation_of_one_source():
    store = GraphStore()
    assign_profile(store.graph, "medicine")
    base = {"subject": "Metformin", "relation": "reduces", "object": "HbA1c", "source": "a"}
    store.add_triple({**base, "condition": "adults"})
    store.add_triple({**base, "condition": "children"})
    assert len(store.graph.get_edge_data("Metformin", "HbA1c")) == 1


def test_finance_merge_keeps_edges_with_other_date():
    store = finance_store()
    store.add_triple({"subject": "VW", "relation": "reports", "object": "revenue", "source": "a", "as_of": "2023"})
    store.add_triple({"subject": "Volkswagen", "relation": "reports", "object": "revenue", "source": "a", "as_of": "2024"})
    stats = store.merge_nodes("Volkswagen", "VW")
    assert stats["moved"] == 1 and len(store.graph.get_edge_data("Volkswagen", "revenue")) == 2


def _finance_store():
    store = GraphStore()
    store.graph.graph["profile"] = "finance"
    return store


def test_finance_sale_is_stored_with_its_reason_and_survives_saving(tmp_path):
    store = _finance_store()
    store.add_triple({"subject": "Pershing Square", "relation": "sells_stake_in", "object": "Chipotle",
                      "value": "gesamte Beteiligung", "condition": "schwache Zahlen", "as_of": "2025"})
    path = str(tmp_path / "graph.gml")
    store.save(path)
    loaded = GraphStore()
    loaded.load(path)
    assert "sells_stake_in" in get_profile("finance").relation_types
    edge = next(iter(loaded.graph["Pershing Square"]["Chipotle"].values()))
    assert (edge["relation"], edge["value"], edge["condition"]) == ("sells_stake_in", "gesamte Beteiligung", "schwache Zahlen")


def test_finance_negation_reaches_the_prompt_and_survives_saving(tmp_path):
    store = _finance_store()
    store.add_triple({"subject": "Kaffeehaus AG", "relation": "forecasts", "object": "Prognose", "negated": "ja"})
    path = str(tmp_path / "graph.gml")
    store.save(path)
    loaded = GraphStore()
    loaded.load(path)
    edge = next(iter(loaded.graph.edges(keys=True)))
    assert "negated: ja" in format_triple(1, loaded.graph, edge)
    assert triple_dict(loaded.graph, edge)["negated"] == "ja"


def test_finance_negation_does_not_replace_the_positive_statement():
    store = _finance_store()
    for negated in (None, "ja"):
        store.add_triple({"subject": "Kaffeehaus AG", "relation": "forecasts", "object": "Prognose",
                          "source": "https://example.org/a", "negated": negated})
    assert len(store.graph["Kaffeehaus AG"]["Prognose"]) == 2
    assert len(_distinct_statements(store.graph, list(store.graph.edges(keys=True)))) == 2


def test_finance_negated_is_only_yes_and_is_not_translated():
    negated = next(q for q in get_profile("finance").qualifiers if q.name == "negated")
    assert negated.pattern == "^ja$" and not negated.translate and negated.description


def test_finance_prompts_cover_sales_negation_and_named_opinions():
    notes = get_profile("finance").prompt_notes
    assert "sells_stake_in" in notes["extract"] and "negated" in notes["extract"] and "Verkaufsregel" in notes["extract"]
    assert "beide Seiten" in notes["answer"] and "nichts vorliegt" in notes["answer"] and "negated" in notes["answer"]
    assert "Keine Anlageempfehlung" in notes["answer"]  # eine eigene Empfehlung bleibt verboten
    assert "keine Anlageempfehlung" in notes["check"] and "negated" in notes["check"]

