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
from graph.ask import build_subgraph, format_triple, triple_dict
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

def test_medicine_keeps_the_edge_fields_of_the_existing_graph():
    fields = ("value", "condition", "evidence_level")
    assert get_profile("medicine").qualifier_fields == fields
    assert get_profile("medicine").detail_fields == fields
    assert get_profile("generic").qualifier_fields == fields


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
