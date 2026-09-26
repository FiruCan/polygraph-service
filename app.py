"""
app.py
------
Graph-Service: haelt einen Wissensgraphen im Speicher (persistiert als
data/graph.gml) und bietet ihn per HTTP an - fuer Ingestion (POST /triples,
z.B. aus polygraph/main.py), Fragen (POST /ask, GraphRAG) und Darstellung
(GET /graph, von static/app.js gerendert).

Start: uvicorn app:app --reload --port 8000
"""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from graph.ask import ask as run_ask
from graph.normalize import normalize_triple
from graph.store import GraphStore

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "graph.gml")

app = FastAPI(title="polygraph-service")
store = GraphStore()
if os.path.exists(DATA_PATH):
    store.load(DATA_PATH)


class TriplesIn(BaseModel):
    triples: list[dict]


class QuestionIn(BaseModel):
    question: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "nodes": store.graph.number_of_nodes(),
        "edges": store.graph.number_of_edges(),
    }


@app.get("/graph")
def get_graph():
    return store.to_json()


@app.post("/triples")
def add_triples(body: TriplesIn):
    merges = []
    for triple in body.triples:
        normalized = normalize_triple(triple, store.known_entities(), store.known_relations())
        for field in ("subject", "object", "relation"):
            if normalized[field] != triple[field]:
                merges.append([field, triple[field], normalized[field]])
        store.add_triple(normalized)

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    store.save(DATA_PATH)

    return {
        "added": len(body.triples),
        "merges": merges,
        "nodes": store.graph.number_of_nodes(),
        "edges": store.graph.number_of_edges(),
    }


@app.post("/ask")
def ask_question(body: QuestionIn):
    return run_ask(store.graph, body.question)


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
