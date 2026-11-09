"""
app.py
------
Graph-Service: haelt einen Wissensgraphen im Speicher (persistiert als
data/<fachgebiet>/graph.gml) und bietet ihn per HTTP an - fuer Ingestion (POST /triples,
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

Fachgebiet: pro Instanz ein Domaenen-Profil (domains/), gewaehlt per
POLYGRAPH_DOMAIN (z.B. "medicine"). Es bestimmt auch den Datenordner
data/<fachgebiet>/ (Graph, Hierarchie, Backups, Uebersetzungs-Cache), so
laufen mehrere Instanzen parallel, ohne sich zu beruehren; eine Sperre
verhindert zwei Instanzen auf demselben Ordner (open_instance). Ohne
POLYGRAPH_DOMAIN startet der Service nicht.

Fragen-Pakete (pakete.py): question_packages/<fachgebiet>/<name>.json (vorgegeben) oder
in Metis hochgeladen (data/<fachgebiet>/question_packages/), von Argos nacheinander
recherchiert; die Antworten schreibt Argos nach
data/<fachgebiet>/antworten/<name>/<lauf>.json, Metis zeigt sie als Dossier.

Start: POLYGRAPH_DOMAIN=medicine uvicorn app:app --port 8000
       POLYGRAPH_DOMAIN=finance uvicorn app:app --port 8060
"""

import fcntl
import os
import shutil
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import graph.localize as label_cache
from domains import assign_profile, get_profile, profile_of
from graph.ask import (DEFAULT_LANGUAGE, ask as run_ask, explain_term, node_edges, search_nodes,
                       select_nodes, triple_dict)
from graph.dedupe import DEDUPE_THRESHOLD, find_duplicates
from graph.localize import localize, translate_texts
from graph.normalize import normalize_triple, similar_entities
from graph.store import GraphStore, hierarchy_path
from graph.suggest import suggest_questions
from graph.translate import TYPE_FIELDS, translate_details, translate_names, translate_types
import pakete

DATA_ROOT = os.path.join(os.path.dirname(__file__), "data")
FRAGEN_ROOT = os.path.join(os.path.dirname(__file__), "question_packages")
# data/<fachgebiet>/graph.gml, gesetzt von open_instance() beim Start
DATA_PATH = None
# question_packages/<fachgebiet>/ (vorgegeben), data/<fachgebiet>/question_packages/ (hochgeladen)
# und data/<fachgebiet>/antworten/, ebenso
FRAGEN_DIR = None
EIGENE_DIR = None
ANTWORTEN_DIR = None

store = GraphStore()
store_lock = threading.Lock()
antworten_lock = threading.Lock()  # eigene Sperre fuer Pakete und Antworten: soll nicht auf /ask warten
_instance_lock = None  # offene .lock-Datei, gehalten, solange der Prozess laeuft


def lock_data_dir(directory: str):
    """
    Exklusive Sperre auf den Datenordner (fcntl.flock auf directory/.lock).
    Zwei Instanzen auf demselben Graphen wuerden sich gegenseitig
    ueberschreiben: jede haelt ihren Stand im Speicher und speichert ihn
    ganz. Die Sperre endet mit dem Prozess, auch nach einem Absturz.
    -> offene Datei (offen halten); RuntimeError, wenn schon gesperrt.
    """
    handle = open(os.path.join(directory, ".lock"), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError(f"{directory} wird schon von einem anderen polygraph-service benutzt")
    return handle


def open_instance(domain: str, root: str = None):
    """
    Beim Start: Datenordner root/<domain>/ waehlen und sperren, Graph laden,
    Profil festlegen, Uebersetzungs-Cache in den Ordner legen. Ein Graph aus
    der Zeit vor den Datenordnern (root/graph.gml) wird nicht verschoben -
    der Start bricht dann mit der Anleitung dazu ab.
    """
    global DATA_PATH, FRAGEN_DIR, EIGENE_DIR, ANTWORTEN_DIR, _instance_lock
    root = root or DATA_ROOT
    if not domain:
        raise RuntimeError("POLYGRAPH_DOMAIN fehlt - z.B. POLYGRAPH_DOMAIN=medicine "
                           "(waehlt Profil und Datenordner data/<fachgebiet>/)")
    get_profile(domain)  # unbekanntes Profil -> ValueError, bevor ein Ordner entsteht
    directory = os.path.join(root, domain)
    path = os.path.join(directory, "graph.gml")
    legacy = os.path.join(root, "graph.gml")
    if os.path.exists(legacy) and not os.path.exists(path):
        raise RuntimeError(f"Graph noch unter {legacy} - erst in den Ordner seines Fachgebiets "
                           f"verschieben, z.B. mkdir -p {directory} && mv {legacy} {directory}/")
    os.makedirs(directory, exist_ok=True)
    _instance_lock = lock_data_dir(directory)
    if os.path.exists(path):
        store.load(path)
    # Ein alter Graph, der hier sein Profil bekommt, wird gleich gespeichert -
    # sonst ginge die Zuordnung bis zum naechsten Import beim Neustart verloren.
    if assign_profile(store.graph, domain) and os.path.exists(path):
        store.save(path)
    label_cache.CACHE_DIR = os.path.join(directory, "labels")
    DATA_PATH = path
    FRAGEN_DIR = os.path.join(FRAGEN_ROOT, domain)
    EIGENE_DIR = os.path.join(directory, "question_packages")
    ANTWORTEN_DIR = os.path.join(directory, "antworten")


@asynccontextmanager
async def lifespan(app):
    # Beim Serverstart, nicht beim Import: Tests (TestClient ohne "with")
    # beruehren so nie einen echten Datenordner.
    open_instance(os.environ.get("POLYGRAPH_DOMAIN"))
    yield


app = FastAPI(title="polygraph-service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=os.environ.get("POLYGRAPH_CORS_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1)(:\d+)?"),
    allow_methods=["GET", "POST", "DELETE"],  # DELETE: eigene Fragenlisten entfernen
    allow_headers=["Content-Type"],
)


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
    field: str  # eine Kanten-Angabe des Profils (detail_fields), geprueft in edges_rewrite
    old: str
    new: str


class EdgeRewriteIn(BaseModel):
    rewrites: list[EdgeRewrite]


class RenameIn(BaseModel):
    kind: Literal["relation", "type"]
    old: str
    new: str


class TypeParentsIn(BaseModel):
    parents: dict[str, Optional[str]]


class PaketIn(BaseModel):
    name: str   # wird zum Dateinamen: nur Buchstaben, Ziffern, _ und -
    paket: dict  # wie question_packages/<fachgebiet>/*.json; Fragen auch als blosse Texte


class AntwortIn(BaseModel):
    kopf: dict = Field(default_factory=dict)  # gilt fuer den ganzen Lauf: modus, gestartet, ...
    eintrag: dict                             # eine Frage mit Antwort, Urteil und Quellen


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
        detail_fields = profile_of(store.graph).detail_fields
        known = set(store.known_entities())
        translate_names([t[f] for t in body.triples for f in ("subject", "object")
                         if isinstance(t.get(f), str) and t[f] not in known], topics=topics)
        translate_details([t[f] for t in body.triples for f in detail_fields
                           if isinstance(t.get(f), str) and t[f].strip()], topics=topics)
        # Typen ebenso; ein schon bekannter Typ ist englisch (Bestand mit
        # translate_graph.py umgestellt) und braucht keinen LLM-Aufruf.
        known_types = set(store.known_types())
        types = translate_types([t[f] for t in body.triples for f in TYPE_FIELDS
                                 if isinstance(t.get(f), str) and t[f].strip() and t[f] not in known_types],
                                topics=topics)

        merges = []
        for triple in body.triples:
            normalized = normalize_triple(triple, store.known_entities(), store.known_relations(),
                                          detail_fields=detail_fields)
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


@app.get("/profile")
def profile():
    """
    Domaenen-Profil dieser Instanz (domains/): Name, Kanten-Angaben
    (qualifiers) und Startvokabular - fuer polygraph (Extraktion) und andere
    Clients. fixed: ob das Profil schon in der graph.gml festgeschrieben ist.
    """
    with store_lock:
        return {**profile_of(store.graph).to_json(), "fixed": "profile" in store.graph.graph}


@app.get("/vocabulary")
def vocabulary():
    """
    Knotentypen und Relationen des Graphen mit Haeufigkeit, haeufigste
    zuerst, dazu die Typ-Hierarchie. polygraph gibt die haeufigen der
    Extraktion als bekanntes Vokabular mit - welche Domain der Graph hat,
    bestimmen die Artikel.
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
    Bei Typen zieht die Typ-Hierarchie mit, auch fuer Typen ohne Knoten.
    """
    with store_lock:
        hierarchy_changed = False
        if body.kind == "relation":
            changed = store.rename_relation(body.old, body.new)
        else:
            changed = store.retype_nodes(body.old, body.new)
            hierarchy_changed = store.rename_type_in_hierarchy(body.old, body.new)
        if changed or hierarchy_changed:
            store.save(DATA_PATH)
        return {"kind": body.kind, "old": body.old, "new": body.new, "changed": changed}


@app.post("/vocabulary/parents")
def vocabulary_parents(body: TypeParentsIn):
    """
    Typ-Hierarchie setzen: pro Typ der Obertyp ("disease": "condition"),
    null entfernt ihn - fuer den Vokabular-Steward in polygraph (nach
    Freigabe durch einen Menschen). Ein Kreis wird abgelehnt (400), dann
    aendert sich nichts.
    """
    with store_lock:
        try:
            changed = store.set_type_parents(body.parents)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if changed:
            store.save(DATA_PATH)
        return {"changed": changed, "type_parents": len(store.type_parents)}


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
    sonst nur durch Neuimport der Quellen rueckgaengig machen liessen. Die
    Typ-Hierarchie wird mitkopiert (graph.backup-<Zeit>.hierarchy.json).
    Landet im Datenordner der Instanz (data/<fachgebiet>/).
    """
    with store_lock:
        store.save(DATA_PATH)
        path = os.path.join(os.path.dirname(DATA_PATH), f"graph.backup-{datetime.now():%Y-%m-%d-%H%M%S}.gml")
        shutil.copy2(DATA_PATH, path)
        if os.path.exists(hierarchy_path(DATA_PATH)):
            shutil.copy2(hierarchy_path(DATA_PATH), hierarchy_path(path))
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
    einmal am Ende. Nur Kanten-Angaben des Profils (detail_fields), sonst 422.
    """
    with store_lock:
        fields = profile_of(store.graph).detail_fields
        unknown = sorted({r.field for r in body.rewrites} - set(fields))
        if unknown:
            raise HTTPException(status_code=422,
                                detail=f"Keine Kanten-Angabe des Profils: {', '.join(unknown)} "
                                       f"(erlaubt: {', '.join(fields)})")
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


@app.get("/nodes/search")
def nodes_search(q: str = Query(..., min_length=1)):
    """Knotennamen, die q enthalten - fuer Agenten ausserhalb des Service (z.B. argos)."""
    with store_lock:
        return {"nodes": search_nodes(store.graph, q)}


@app.get("/nodes/neighbors")
def nodes_neighbors(node: str, limit: int = Query(40, ge=1, le=500)):
    """
    Ein- und ausgehende Tripel eines Knotens (sicherste zuerst) und seine
    Nachbarn. Der Name kommt als Query-Parameter, weil Knotennamen "/"
    enthalten koennen.
    """
    with store_lock:
        graph = store.graph
        if node not in graph.nodes:
            raise HTTPException(status_code=404, detail=f"Knoten '{node}' existiert nicht")
        edges = node_edges(graph, node)[:limit]
        neighbors = list(dict.fromkeys(v if u == node else u for u, v, _ in edges))
        return {
            "node": node,
            "type": graph.nodes[node].get("type"),
            "triples": [triple_dict(graph, e) for e in edges],
            "neighbors": neighbors,
        }


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


@app.get("/fragen")
def fragen_list():
    """Fragen-Pakete dieses Fachgebiets (vorgegebene und hochgeladene) mit dem letzten Antwort-Lauf."""
    with antworten_lock:
        return {"pakete": pakete.list_pakete(FRAGEN_DIR, ANTWORTEN_DIR, EIGENE_DIR)}


@app.post("/fragen")
def fragen_upload(body: PaketIn):
    """Ein eigenes Paket hochladen (Metis) - ersetzt ein gleichnamiges eigenes, nie ein vorgegebenes."""
    with antworten_lock:
        try:
            return pakete.save_paket(FRAGEN_DIR, EIGENE_DIR, body.name, body.paket)
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"'{body.name}' ist ein vorgegebenes Paket - "
                                                        "bitte einen anderen Namen waehlen")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@app.get("/fragen/{name}")
def fragen_get(name: str):
    """Ein Paket mit allen Fragen - Argos holt es sich beim Start."""
    try:
        return pakete.load_paket(FRAGEN_DIR, name, EIGENE_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Fragen-Paket '{name}' gibt es nicht")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Fragen-Paket '{name}' ist kein gueltiges JSON: {e}")


@app.delete("/fragen/{name}")
def fragen_delete(name: str):
    """Ein hochgeladenes Paket loeschen; seine Antwort-Laeufe bleiben im Datenordner."""
    with antworten_lock:
        try:
            pakete.delete_paket(EIGENE_DIR, name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Eigenes Paket '{name}' gibt es nicht")
    return {"deleted": name}


@app.get("/fragen/{name}/antworten")
def antworten_list(name: str):
    """Die Antwort-Laeufe eines Pakets, neueste zuerst, je mit Zahl der Urteile."""
    with antworten_lock:
        return {"laeufe": pakete.list_laeufe(ANTWORTEN_DIR, name)}


@app.get("/fragen/{name}/antworten/{lauf}")
def antworten_get(name: str, lauf: str):
    """Ein Lauf: alle Antworten, wie Argos sie nach jeder Frage geschrieben hat."""
    with antworten_lock:
        try:
            return pakete.load_lauf(ANTWORTEN_DIR, name, lauf)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Lauf '{lauf}' von '{name}' gibt es nicht")


@app.post("/fragen/{name}/antworten/{lauf}")
def antworten_save(name: str, lauf: str, body: AntwortIn):
    """Eine Antwort speichern (Argos, nach jeder Frage) - ersetzt eine fruehere mit derselben id."""
    with antworten_lock:
        try:
            return pakete.save_antwort(ANTWORTEN_DIR, name, lauf, body.kopf, body.eintrag)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@app.get("/help", include_in_schema=False)
def help_page():
    """Kurzer Einstieg: leitet auf die automatische API-Doku (/docs) weiter."""
    return RedirectResponse("/docs")
