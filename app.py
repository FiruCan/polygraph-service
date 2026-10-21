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
import shutil
import threading
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from graph.ask import DEFAULT_LANGUAGE, ask as run_ask, explain_term, select_nodes
from graph.dedupe import DEDUPE_THRESHOLD, find_duplicates
from graph.localize import localize, translate_texts
from graph.normalize import normalize_triple, similar_entities
from graph.store import GraphStore
from graph.suggest import suggest_questions
from graph.translate import DETAIL_FIELDS, TYPE_FIELDS, translate_details, translate_names, translate_types

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


# Sprache von Fragen und Antworten, frei waehlbar ("Deutsch", "Englisch",
# "Tuerkisch", ...) - der Graph selbst ist immer englisch.
Language = Field(DEFAULT_LANGUAGE, min_length=2, max_length=40)


class QuestionIn(BaseModel):
    question: str
    language: str = Language


class ExplainIn(BaseModel):
    term: str
    type: Optional[str] = None
    question: str = ""
    answer: str = ""
    passages: list[str] = []
    language: str = Language


class LabelsIn(BaseModel):
    texts: list[str] = Field(..., max_length=20000)
    language: str = Language
    cached_only: bool = False


class TranslateIn(BaseModel):
    texts: list[str] = Field(..., max_length=200)
    language: str = Language


class SimilarIn(BaseModel):
    names: list[str]
    limit: int = 3


class DuplicatesIn(BaseModel):
    threshold: float = Field(DEDUPE_THRESHOLD, ge=0.5, le=1.0)
    limit: Optional[int] = Field(None, ge=1)


class MergeIn(BaseModel):
    keep: str
    remove: str


class NodeRename(BaseModel):
    old: str
    new: str


class NodeRenameIn(BaseModel):
    renames: list[NodeRename]


class EdgeRewrite(BaseModel):
    field: Literal["value", "condition", "evidence_level"]
    old: str
    new: str


class EdgeRewriteIn(BaseModel):
    rewrites: list[EdgeRewrite]


class RenameIn(BaseModel):
    kind: Literal["relation", "type"]
    old: str
    new: str


@app.get("/health")
def health():
    """Lebenszeichen plus Groesse des Graphen (Knoten, Kanten)."""
    with store_lock:
        return {
            "status": "ok",
            "nodes": store.graph.number_of_nodes(),
            "edges": store.graph.number_of_edges(),
        }


@app.get("/graph")
def get_graph():
    """Der ganze Graph als JSON: nodes und edges."""
    with store_lock:
        return store.to_json()


@app.post("/triples")
def add_triples(body: TriplesIn):
    """
    Tripel normalisieren und einfuegen. Mit source werden vorher alle Kanten
    dieser Quelle entfernt (Re-Import ersetzt statt zu wachsen).
    """
    with store_lock:
        removed_nodes_before = store.graph.number_of_nodes()
        removed_edges_before = store.graph.number_of_edges()
        if body.source:
            store.remove_edges_by_source(body.source)
        removed = {
            "nodes": removed_nodes_before - store.graph.number_of_nodes(),
            "edges": removed_edges_before - store.graph.number_of_edges(),
        }

        # Alle neuen Namen und Angaben vorab in wenigen Paketen uebersetzen
        # (der Graph ist immer englisch) - normalize_triple findet sie dann
        # im Cache statt einen LLM-Aufruf pro Feld zu machen.
        # Das Fachgebiet fuer mehrdeutige Woerter ergibt sich aus dem Graphen
        # und den neuen Tripeln selbst, nicht aus einer festen Domain.
        topics = store.topics(t.get(f) for t in body.triples for f in TYPE_FIELDS)
        known = set(store.known_entities())
        translate_names([t[f] for t in body.triples for f in ("subject", "object")
                         if isinstance(t.get(f), str) and t[f] not in known], topics=topics)
        translate_details([t[f] for t in body.triples for f in DETAIL_FIELDS
                           if isinstance(t.get(f), str) and t[f].strip()], topics=topics)
        # Typen ebenso; ein schon bekannter Typ ist englisch (Bestand mit
        # translate_graph.py umgestellt) und braucht keinen LLM-Aufruf.
        known_types = set(store.known_types())
        types = translate_types([t[f] for t in body.triples for f in TYPE_FIELDS
                                 if isinstance(t.get(f), str) and t[f].strip() and t[f] not in known_types],
                                topics=topics)

        merges = []
        for triple in body.triples:
            normalized = normalize_triple(triple, store.known_entities(), store.known_relations())
            for field in TYPE_FIELDS:
                if isinstance(triple.get(field), str) and triple[field] in types:
                    normalized[field] = types[triple[field]]
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


@app.get("/vocabulary")
def vocabulary():
    """
    Knotentypen und Relationen des Graphen mit Haeufigkeit, haeufigste
    zuerst. polygraph gibt die haeufigen der Extraktion als bekanntes
    Vokabular mit - welche Domain der Graph hat, bestimmen die Artikel.
    """
    with store_lock:
        return store.vocabulary()


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


@app.post("/duplicates/find")
def duplicates_find(body: DuplicatesIn):
    """
    Duplikat-Aufraeumer (graph/dedupe.py): Vorschlaege fuer doppelte Knoten,
    freigegeben, wenn die Namen es belegen; nichts wird geaendert. Dauert
    lange (~1 Std. bei ~3.000 Knoten) - laeuft deshalb auf einer Kopie, damit
    Importe und Fragen nicht so lange warten.
    """
    with store_lock:
        graph = store.graph.copy()
    return find_duplicates(graph, threshold=body.threshold, limit=body.limit)


@app.post("/nodes/merge")
def nodes_merge(body: MergeIn):
    """Knoten 'remove' in 'keep' zusammenfuehren (nach Freigabe - durch den Duplikat-Agenten oder einen Menschen)."""
    with store_lock:
        try:
            stats = store.merge_nodes(body.keep, body.remove)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"Knoten nicht gefunden: {e.args[0]}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        store.save(DATA_PATH)
        return {"keep": body.keep, "remove": body.remove, **stats,
                "nodes": store.graph.number_of_nodes(), "edges": store.graph.number_of_edges()}


@app.post("/graph/backup")
def graph_backup():
    """
    Kopie des Graphen mit Zeitstempel (wie translate_graph.py apply) - vor
    automatischen Zusammenfuehrungen (polygraph dedupe.py --auto), die sich
    sonst nur durch Neuimport der Quellen rueckgaengig machen liessen.
    """
    with store_lock:
        store.save(DATA_PATH)
        path = os.path.join(os.path.dirname(DATA_PATH), f"graph.backup-{datetime.now():%Y-%m-%d-%H%M%S}.gml")
        shutil.copy2(DATA_PATH, path)
    return {"backup": os.path.basename(path)}


@app.post("/nodes/rename")
def nodes_rename(body: NodeRenameIn):
    """
    Knoten umbenennen (Umstellung auf englische Namen, translate_graph.py);
    existiert der neue Name schon, werden beide zusammengefuehrt. Viele auf
    einmal, gespeichert wird nur einmal am Ende. Fehlt ein Knoten (z.B.
    schon umbenannt), wird er uebersprungen statt alles abzubrechen.
    """
    with store_lock:
        renamed, merged, skipped = 0, 0, []
        for r in body.renames:
            try:
                stats = store.rename_node(r.old, r.new)
            except (KeyError, ValueError) as e:
                skipped.append({"old": r.old, "new": r.new, "reason": str(e)})
                continue
            merged += stats["merged"]
            renamed += not stats["merged"]
        if renamed or merged:
            store.save(DATA_PATH)
        return {"renamed": renamed, "merged": merged, "skipped": skipped,
                "nodes": store.graph.number_of_nodes(), "edges": store.graph.number_of_edges()}


@app.post("/edges/rewrite")
def edges_rewrite(body: EdgeRewriteIn):
    """
    Angaben an Kanten ersetzen (Umstellung auf Englisch, translate_graph.py):
    jede Kante, deren Feld genau 'old' ist, bekommt 'new'. Gespeichert wird
    einmal am Ende.
    """
    with store_lock:
        changed = sum(store.rewrite_edge_field(r.field, r.old, r.new) for r in body.rewrites)
        if changed:
            store.save(DATA_PATH)
        return {"changed": changed}


@app.get("/questions/suggest")
def questions_suggest(count: int = Query(5, ge=1, le=10),
                      language: str = Query(DEFAULT_LANGUAGE, min_length=2, max_length=40),
                      topic: str = Query("", max_length=500)):
    """
    Beispielfragen aus dem Graphen (graph/suggest.py). Arbeitet auf einer
    Kopie: der LLM-Aufruf dauert ~10-20 s, so lange soll ein gleichzeitiger
    Import (POST /triples) nicht warten muessen.

    Mit topic (Thema in beliebiger Sprache) waehlt das LLM erst die passenden
    (englischen) Knoten, und alle Fragen drehen sich um diese. Passt kein
    Knoten, gibt es keine Fragen statt zufaelliger - topic_nodes ist dann leer.
    """
    with store_lock:
        graph = store.graph.copy()
    topic = topic.strip()
    if not topic:
        return {"questions": suggest_questions(graph, count, language=language)}
    focus = select_nodes(graph, topic) if graph.number_of_nodes() else []
    questions = suggest_questions(graph, count, language=language, focus=focus) if focus else []
    return {"questions": questions, "topic_nodes": focus}



@app.post("/ask")
def ask_question(body: QuestionIn):
    """Frage an den Graphen (GraphRAG): Antwort, verwendete Tripel und Teilgraph."""
    with store_lock:
        return run_ask(store.graph, body.question, language=body.language)


@app.post("/explain")
def explain(body: ExplainIn):
    """
    Ausfuehrliche Erklaerung eines Begriffs aus der Antwort (Allgemeinwissen
    des Modells, nicht aus dem Graphen). Ohne store_lock: liest den Graphen nicht.
    """
    try:
        return explain_term(body.term, body.question, body.answer, body.type, body.passages,
                            language=body.language)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erklaerung fehlgeschlagen: {e}")


@app.post("/labels")
def labels(body: LabelsIn):
    """
    Beschriftungen des Graphen (Knoten, Typen, Beziehungen, Kanten-Angaben)
    in der Sprache des Lesers, nur fuer die Anzeige (graph/localize.py).
    cached_only=true: nur schon Uebersetztes, sofort. store_lock nur kurz fuer
    das Fachgebiet (haeufigste Typen), nicht waehrend der Uebersetzung.
    """
    with store_lock:
        topics = store.topics()
    try:
        return {"labels": localize(body.texts, body.language, cached_only=body.cached_only, topics=topics)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Uebersetzung fehlgeschlagen: {e}")


@app.post("/translate")
def translate(body: TranslateIn):
    """
    Freie Texte in die Sprache des Lesers (graph/localize.py): eine schon
    gegebene Antwort samt Pruefung und Glossar, wenn er die Sprache wechselt.
    -> {"texts": [...]} in derselben Reihenfolge. Ohne store_lock: liest den
    Graphen nicht.
    """
    try:
        return {"texts": translate_texts(body.texts, body.language)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Uebersetzung fehlgeschlagen: {e}")


@app.get("/help", include_in_schema=False)
def help_page():
    """Kurzer Einstieg: leitet auf die automatische API-Doku (/docs) weiter."""
    return RedirectResponse("/docs")
