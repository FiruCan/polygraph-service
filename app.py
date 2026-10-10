"""
app.py
------
Graph-Service: haelt einen Wissensgraphen im Speicher (persistiert als
data/graph.gml) und bietet ihn per HTTP an - fuer Ingestion (POST /triples,
z.B. aus polygraph/main.py), Fragen (POST /ask, GraphRAG) und Darstellung
(GET /graph, von static/app.js gerendert).

FastAPI fuehrt synchrone Routen in einem Thread-Pool aus - bei mehreren
gleichzeitigen Requests (z.B. zwei Clients, oder du + ein Skript) wuerden
sonst mehrere Threads denselben NetworkX-Graphen gleichzeitig mutieren, was
NetworkX nicht absichert. store_lock serialisiert deshalb jeden Zugriff.

CORS: Ein Frontend auf einem anderen Port (z.B. deine Oberflaeche auf 8000
fragt die Kollegen-Instanz auf 8001 ab) braucht die Erlaubnis des
abgefragten Service. Standard: jede Seite von localhost/127.0.0.1, beliebiger
Port. Andere Herkuenfte per Umgebungsvariable POLYGRAPH_CORS_ORIGIN_REGEX.

Start: uvicorn app:app --reload --port 8000
"""

import os
import threading
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from graph.ask import ask as run_ask
from graph.normalize import normalize_triple
from graph.store import GraphStore

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "graph.gml")

app = FastAPI(title="polygraph-service")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=os.environ.get("POLYGRAPH_CORS_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1)(:\d+)?"),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
store = GraphStore()
store_lock = threading.Lock()
if os.path.exists(DATA_PATH):
    store.load(DATA_PATH)


class TriplesIn(BaseModel):
    triples: list[dict]
    source: Optional[str] = None


class QuestionIn(BaseModel):
    question: str


@app.get("/health")
def health():
    with store_lock:
        return {
            "status": "ok",
            "nodes": store.graph.number_of_nodes(),
            "edges": store.graph.number_of_edges(),
        }


@app.get("/graph")
def get_graph():
    with store_lock:
        return store.to_json()


@app.post("/triples")
def add_triples(body: TriplesIn):
    with store_lock:
        removed_nodes_before = store.graph.number_of_nodes()
        removed_edges_before = store.graph.number_of_edges()
        if body.source:
            store.remove_edges_by_source(body.source)
        removed = {
            "nodes": removed_nodes_before - store.graph.number_of_nodes(),
            "edges": removed_edges_before - store.graph.number_of_edges(),
        }

        merges = []
        for triple in body.triples:
            normalized = normalize_triple(triple, store.known_entities(), store.known_relations())
            for field in ("subject", "object", "relation"):
                if normalized[field] != triple[field]:
                    merges.append([field, triple[field], normalized[field]])
            if body.source:
                normalized["source"] = body.source
            store.add_triple(normalized)

        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        store.save(DATA_PATH)

        return {
            "added": len(body.triples),
            "removed_from_source": removed if body.source else None,
            "merges": merges,
            "nodes": store.graph.number_of_nodes(),
            "edges": store.graph.number_of_edges(),
        }


@app.post("/ask")
def ask_question(body: QuestionIn):
    with store_lock:
        return run_ask(store.graph, body.question)


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
