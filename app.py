"""
app.py
------
Graph-Service: haelt einen Wissensgraphen im Speicher (persistiert als
data/graph.gml) und bietet ihn per HTTP an - fuer Ingestion (POST /triples,
z.B. aus polygraph/main.py), Fragen (POST /ask, GraphRAG) und Darstellung
(GET /graph). Reine API ohne eigene Oberflaeche - die Weboberflaeche liegt in
polygraph (kg/, ausgeliefert von ingest_app.py auf http://localhost:8001).

FastAPI fuehrt synchrone Routen in einem Thread-Pool aus - bei mehreren
gleichzeitigen Requests (z.B. zwei Clients, oder du + ein Skript) wuerden
sonst mehrere Threads denselben NetworkX-Graphen gleichzeitig mutieren, was
NetworkX nicht absichert. store_lock serialisiert deshalb jeden Zugriff.

CORS: Die Oberflaeche laeuft auf einem anderen Port (polygraph, 8001) und
fragt diesen Service oder eine Kollegen-Instanz ab - dafuer braucht sie die
Erlaubnis des abgefragten Service. Standard: jede Seite von localhost/127.0.0.1, beliebiger
Port. Andere Herkuenfte per Umgebungsvariable POLYGRAPH_CORS_ORIGIN_REGEX.

Start: uvicorn app:app --reload --port 8000
"""

import os
import threading
from urllib.parse import quote
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph.ask import ask as run_ask
import graph.export as export_module
from graph.export import export_answer
from graph.normalize import normalize_triple, similar_entities
from graph.store import GraphStore
from graph.suggest import suggest_questions

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


class SimilarIn(BaseModel):
    names: list[str]
    limit: int = 3


class ExportIn(BaseModel):
    question: str
    answer: str
    selected_nodes: list[str] = []
    triples: list[dict] = []
    service: Optional[str] = None


class RenameIn(BaseModel):
    kind: Literal["relation", "type"]
    old: str
    new: str


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


@app.post("/entities/similar")
def entities_similar(body: SimilarIn):
    """Entity-Linking-Hinweise fuer polygraph: aehnliche, schon bekannte Knoten pro Name."""
    with store_lock:
        return {"matches": similar_entities(body.names, store.known_entities(), body.limit)}


@app.post("/vocabulary/rename")
def vocabulary_rename(body: RenameIn):
    """
    Relation bzw. Knotentyp im ganzen Graphen umbenennen - fuer den
    Vokabular-Steward in polygraph (nach Freigabe durch einen Menschen).
    """
    with store_lock:
        if body.kind == "relation":
            changed = store.rename_relation(body.old, body.new)
        else:
            changed = store.retype_nodes(body.old, body.new)
        if changed:
            store.save(DATA_PATH)
        return {"kind": body.kind, "old": body.old, "new": body.new, "changed": changed}


@app.get("/questions/suggest")
def questions_suggest(count: int = Query(5, ge=1, le=10)):
    """
    Beispielfragen aus dem Graphen (graph/suggest.py). Arbeitet auf einer
    Kopie: der LLM-Aufruf dauert ~10-20 s, so lange soll ein gleichzeitiger
    Import (POST /triples) nicht warten muessen.
    """
    with store_lock:
        graph = store.graph.copy()
    return {"questions": suggest_questions(graph, count)}


@app.post("/export/pdf")
def export_pdf(body: ExportIn):
    """
    Antwort als PDF nach output/<Frage>.pdf (graph/export.py). Bekommt die
    Daten vom Frontend, statt die Frage neu zu stellen - das PDF zeigt genau
    die Antwort, die man gerade sieht.
    """
    path = export_answer(body.question, body.answer, body.selected_nodes, body.triples, body.service)
    filename = os.path.basename(path)
    return {
        "path": os.path.relpath(path, os.path.dirname(__file__)),
        "absolute_path": os.path.abspath(path),
        "filename": filename,
        "url": f"/output/{quote(filename)}",
    }


@app.get("/output/{filename}")
def output_file(filename: str):
    """Exportierte PDFs zum Oeffnen im Browser - nur Dateien direkt in output/."""
    output_dir = os.path.abspath(export_module.OUTPUT_DIR)
    path = os.path.abspath(os.path.join(output_dir, filename))
    if os.path.dirname(path) != output_dir or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(path, media_type="application/pdf")


@app.post("/ask")
def ask_question(body: QuestionIn):
    with store_lock:
        return run_ask(store.graph, body.question)

