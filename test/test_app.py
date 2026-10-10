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
