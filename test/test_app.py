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
    with patch("app.normalize_triple", side_effect=lambda t, e, r: dict(t)):
        yield TestClient(app_module.app)


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


def test_questions_suggest_rejects_too_many(client):
    assert client.get("/questions/suggest?count=50").status_code == 422


def test_export_pdf_writes_file_named_after_question(client, tmp_path, monkeypatch):
    import graph.export
    monkeypatch.setattr(graph.export, "OUTPUT_DIR", str(tmp_path / "output"))
    r = client.post("/export/pdf", json={
        "question": "Was senkt Krebs?", "answer": "Krafttraining [1].",
        "selected_nodes": ["Krebs"],
        "triples": [{"n": 1, "subject": "Krafttraining", "relation": "reduces_risk_of", "object": "Krebs"}],
    })
    assert r.status_code == 200
    assert r.json()["filename"] == "Was senkt Krebs.pdf"
    assert os.path.exists(tmp_path / "output" / "Was senkt Krebs.pdf")


def test_export_pdf_requires_question_and_answer(client):
    assert client.post("/export/pdf", json={"question": "x"}).status_code == 422


def test_exported_pdf_can_be_opened(client, tmp_path, monkeypatch):
    import graph.export
    monkeypatch.setattr(graph.export, "OUTPUT_DIR", str(tmp_path / "output"))
    out = client.post("/export/pdf", json={"question": "Was hilft gegen Fatigue?", "answer": "x"}).json()
    assert out["absolute_path"].endswith("Was hilft gegen Fatigue.pdf")
    r = client.get(out["url"])
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_output_route_rejects_path_traversal(client, tmp_path, monkeypatch):
    import graph.export
    monkeypatch.setattr(graph.export, "OUTPUT_DIR", str(tmp_path / "output"))
    (tmp_path / "geheim.txt").write_text("x")
    assert client.get("/output/..%2Fgeheim.txt").status_code == 404
    assert client.get("/output/gibtsnicht.pdf").status_code == 404
