"""
API-Tests fuer app.py (FastAPI TestClient). Normalisierung und Ollama sind
gemockt. app.py laedt/speichert sonst direkt data/graph.gml - die Fixture
leitet das auf eine temporaere Datei um, damit Tests nie den echten
Graphen anfassen.
"""

import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as app_module
from graph.store import GraphStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_PATH", str(tmp_path / "graph.gml"))
    monkeypatch.setattr(app_module, "store", GraphStore())
    # Normalisierung ohne Ollama: Begriffe bleiben, wie sie sind
    with patch("app.normalize_triple", side_effect=lambda t, e, r: dict(t)), \
         patch("app.translate_names") as names, patch("app.translate_details") as details:
        client = TestClient(app_module.app)
        client.translate_names, client.translate_details = names, details
        yield client


def triple(subject="Krafttraining", obj="Krebs", relation="reduces_risk_of"):
    return {"subject": subject, "relation": relation, "object": obj}


def test_health_empty(client):
    assert client.get("/health").json() == {"status": "ok", "nodes": 0, "edges": 0}


def test_post_triples_adds_and_persists(client):
    r = client.post("/triples", json={"triples": [triple()], "source": "A"})
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1
    assert body["nodes"] == 2 and body["edges"] == 1
    assert body["removed_from_source"] == {"nodes": 0, "edges": 0}
    assert os.path.exists(app_module.DATA_PATH)


def test_reimport_same_source_replaces_instead_of_growing(client):
    client.post("/triples", json={"triples": [triple(), triple(obj="Diabetes")], "source": "A"})
    r = client.post("/triples", json={"triples": [triple()], "source": "A"}).json()
    assert r["removed_from_source"] == {"nodes": 3, "edges": 2}
    assert r["nodes"] == 2 and r["edges"] == 1


def test_reimport_keeps_other_sources(client):
    client.post("/triples", json={"triples": [triple(subject="Rauchen")], "source": "B"})
    client.post("/triples", json={"triples": [triple()], "source": "A"})
    r = client.post("/triples", json={"triples": [], "source": "A"}).json()
    assert r["nodes"] == 2 and r["edges"] == 1  # nur noch Rauchen -> Krebs


def test_without_source_nothing_is_removed(client):
    client.post("/triples", json={"triples": [triple()]})
    r = client.post("/triples", json={"triples": [triple(obj="Diabetes")]}).json()
    assert r["removed_from_source"] is None
    assert r["edges"] == 2


def test_merges_are_reported(client):
    renamed = lambda t, e, r: {**t, "subject": "Interleukin-6"} if t["subject"] == "IL-6" else dict(t)
    with patch("app.normalize_triple", side_effect=renamed):
        r = client.post("/triples", json={"triples": [triple(subject="IL-6")]}).json()
    assert r["merges"] == [["subject", "IL-6", "Interleukin-6"]]


def test_get_graph_returns_origin(client):
    client.post("/triples", json={"triples": [triple()], "source": "https://example.org"})
    data = client.get("/graph").json()
    assert data["edges"][0]["origin"] == "https://example.org"


def test_post_triples_rejects_missing_body_field(client):
    assert client.post("/triples", json={"source": "A"}).status_code == 422


def test_ask_delegates_to_graphrag(client):
    with patch("app.run_ask", return_value={"answer": "x"}) as ask:
        r = client.post("/ask", json={"question": "Was senkt Krebs?"})
    assert r.json() == {"answer": "x"}
    assert ask.call_args.args[1] == "Was senkt Krebs?"
    assert ask.call_args.kwargs["language"] == "Deutsch"  # Standard


def test_ask_passes_chosen_language(client):
    with patch("app.run_ask", return_value={"answer": "x"}) as ask:
        client.post("/ask", json={"question": "Kanseri ne azaltır?", "language": "Türkisch"})
    assert ask.call_args.kwargs["language"] == "Türkisch"


def test_cors_allows_other_localhost_port(client):
    r = client.get("/health", headers={"Origin": "http://localhost:8001"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:8001"


def test_cors_rejects_foreign_origin(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_entities_similar_uses_known_entities(client):
    client.post("/triples", json={"triples": [triple(subject="Interleukin-6")]})
    with patch("app.similar_entities", return_value={"IL6": ["Interleukin-6"]}) as sim:
        r = client.post("/entities/similar", json={"names": ["IL6"]})
    assert r.json() == {"matches": {"IL6": ["Interleukin-6"]}}
    assert set(sim.call_args.args[1]) == {"Interleukin-6", "Krebs"}


def test_vocabulary_rename_relation_persists(client):
    client.post("/triples", json={"triples": [triple(relation="lowers")]})
    r = client.post("/vocabulary/rename", json={"kind": "relation", "old": "lowers", "new": "reduces_risk_of"})
    assert r.json()["changed"] == 1
    assert client.get("/graph").json()["edges"][0]["relation"] == "reduces_risk_of"
    reloaded = GraphStore()
    reloaded.load(app_module.DATA_PATH)
    assert reloaded.known_relations() == ["reduces_risk_of"]


def test_vocabulary_rename_type(client):
    client.post("/triples", json={"triples": [{**triple(), "object_type": "illness"}]})
    r = client.post("/vocabulary/rename", json={"kind": "type", "old": "illness", "new": "disease"})
    assert r.json()["changed"] == 1


def test_vocabulary_rename_rejects_unknown_kind(client):
    r = client.post("/vocabulary/rename", json={"kind": "entity", "old": "a", "new": "b"})
    assert r.status_code == 422


def test_questions_suggest_returns_list(client):
    client.post("/triples", json={"triples": [triple()]})
    with patch("app.suggest_questions", return_value=[{"question": "Was senkt Krebs?", "type": "knoten", "nodes": ["Krebs"]}]) as sug:
        r = client.get("/questions/suggest?count=3")
    assert r.json() == {"questions": [{"question": "Was senkt Krebs?", "type": "knoten", "nodes": ["Krebs"]}]}
    assert sug.call_args.args[1] == 3
    assert sug.call_args.args[0] is not app_module.store.graph  # arbeitet auf einer Kopie
    assert sug.call_args.kwargs["language"] == "Deutsch"


def test_questions_suggest_passes_language(client):
    with patch("app.suggest_questions", return_value=[]) as sug:
        client.get("/questions/suggest?language=Englisch")
    assert sug.call_args.kwargs["language"] == "Englisch"


def test_questions_suggest_rejects_too_many(client):
    assert client.get("/questions/suggest?count=50").status_code == 422


def test_help_redirects_to_docs(client):
    response = client.get("/help", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_explain_endpoint(client):
    with patch("app.explain_term", return_value={"term": "X", "explanation": "E", "known": True}) as fn:
        r = client.post("/explain", json={"term": "X", "question": "F", "answer": "A"})
    assert r.status_code == 200 and r.json()["explanation"] == "E"
    fn.assert_called_once_with("X", "F", "A", None, [], language="Deutsch")


def test_explain_endpoint_llm_failure_is_502(client):
    with patch("app.explain_term", side_effect=RuntimeError("down")):
        assert client.post("/explain", json={"term": "X"}).status_code == 502


def test_labels_endpoint(client):
    with patch("app.localize", return_value={"muscles": "Muskeln"}) as fn:
        r = client.post("/labels", json={"texts": ["muscles"], "language": "Deutsch", "cached_only": True})
    assert r.status_code == 200 and r.json() == {"labels": {"muscles": "Muskeln"}}
    fn.assert_called_once_with(["muscles"], "Deutsch", cached_only=True)


def test_labels_endpoint_llm_failure_is_502(client):
    with patch("app.localize", side_effect=RuntimeError("down")):
        assert client.post("/labels", json={"texts": ["x"]}).status_code == 502


def test_translate_endpoint(client):
    with patch("app.translate_texts", return_value=["Muscles"]) as fn:
        r = client.post("/translate", json={"texts": ["Muskeln"], "language": "Englisch"})
    assert r.status_code == 200 and r.json() == {"texts": ["Muscles"]}
    fn.assert_called_once_with(["Muskeln"], "Englisch")


def test_translate_endpoint_llm_failure_is_502(client):
    with patch("app.translate_texts", side_effect=RuntimeError("down")):
        assert client.post("/translate", json={"texts": ["x"]}).status_code == 502


# --- Duplikat-Aufraeumer ----------------------------------------------------

def test_nodes_merge(client):
    client.post("/triples", json={"triples": [triple("MS", "Fatigue", "causes"),
                                              triple("multiple Sklerose", "Fatigue", "causes")], "source": "A"})
    r = client.post("/nodes/merge", json={"keep": "multiple Sklerose", "remove": "MS"})
    assert r.status_code == 200
    body = r.json()
    assert body["collapsed"] == 1 and body["nodes"] == 2 and body["edges"] == 1
    assert "MS" not in [n["id"] for n in client.get("/graph").json()["nodes"]]


def test_nodes_merge_errors(client):
    client.post("/triples", json={"triples": [triple()]})
    assert client.post("/nodes/merge", json={"keep": "Krebs", "remove": "gibtsnicht"}).status_code == 404
    assert client.post("/nodes/merge", json={"keep": "Krebs", "remove": "Krebs"}).status_code == 400


def test_duplicates_find_passes_parameters(client):
    with patch("app.find_duplicates", return_value={"vorschlaege": []}) as find:
        r = client.post("/duplicates/find", json={"threshold": 0.8, "limit": 3})
    assert r.status_code == 200
    assert find.call_args.kwargs == {"threshold": 0.8, "limit": 3}
    assert client.post("/duplicates/find", json={"threshold": 0.1}).status_code == 422


# --- Umstellung auf englische Knotennamen -----------------------------------

def test_nodes_rename_renames_merges_and_skips(client):
    client.post("/triples", json={"triples": [triple("Krafttraining", "Krebs"),
                                              triple("strength training", "Fatigue", "reduces")]})
    r = client.post("/nodes/rename", json={"renames": [
        {"old": "Krebs", "new": "cancer"},
        {"old": "Krafttraining", "new": "strength training"},
        {"old": "gibtsnicht", "new": "x"},
    ]})
    body = r.json()
    assert (body["renamed"], body["merged"], len(body["skipped"])) == (1, 1, 1)
    nodes = {n["id"] for n in client.get("/graph").json()["nodes"]}
    assert nodes == {"cancer", "strength training", "Fatigue"}


def test_post_triples_pretranslates_new_names_and_details(client):
    client.post("/triples", json={"triples": [triple("Krafttraining", "Krebs")]})
    client.post("/triples", json={"triples": [dict(triple("Krafttraining", "Muskeln"),
                                                   value="20 Prozent", condition=" ")]})
    assert client.translate_names.call_args.args[0] == ["Muskeln"]  # bekannter Knoten nicht
    assert client.translate_details.call_args.args[0] == ["20 Prozent"]  # leere Angabe nicht


def test_edges_rewrite(client):
    client.post("/triples", json={"triples": [dict(triple(), evidence_level="Metaanalyse")]})
    r = client.post("/edges/rewrite", json={"rewrites": [
        {"field": "evidence_level", "old": "Metaanalyse", "new": "meta-analysis"}]})
    assert r.json() == {"changed": 1}
    assert client.get("/graph").json()["edges"][0]["evidence_level"] == "meta-analysis"
    assert client.post("/edges/rewrite", json={"rewrites": [
        {"field": "relation", "old": "a", "new": "b"}]}).status_code == 422


def test_questions_suggest_with_topic_uses_selected_nodes(client):
    client.post("/triples", json={"triples": [triple()]})
    with patch("app.select_nodes", return_value=["Krebs"]) as sel, \
         patch("app.suggest_questions", return_value=[]) as sug:
        r = client.get("/questions/suggest?topic=Krebsrisiko")
    assert sel.call_args.args[1] == "Krebsrisiko"
    assert sug.call_args.kwargs["focus"] == ["Krebs"]
    assert r.json() == {"questions": [], "topic_nodes": ["Krebs"]}


def test_questions_suggest_unknown_topic_gives_no_questions(client):
    client.post("/triples", json={"triples": [triple()]})
    with patch("app.select_nodes", return_value=[]), patch("app.suggest_questions") as sug:
        r = client.get("/questions/suggest?topic=Raumfahrt")
    sug.assert_not_called()  # keine Zufallsfragen, wenn das Thema nicht im Graphen ist
    assert r.json() == {"questions": [], "topic_nodes": []}


def test_questions_suggest_blank_topic_is_random(client):
    with patch("app.select_nodes") as sel, patch("app.suggest_questions", return_value=[]):
        r = client.get("/questions/suggest?topic=%20%20")
    sel.assert_not_called()
    assert r.json() == {"questions": []}
