# Progress

## Stand

**Aus polygraph ausgelagert (fertig)**
- Grund: zweiter echter Nutzer (Kollege mit eigenem Graph), Graph soll
  wachsen koennen, beide wollen ihre Graphen getrennt aber gemeinsam
  abfragbar machen (gleiche API, keine Vermischung der Domains).
- Uebernommen 1:1 aus `polygraph`: `graph/store.py` (vorher
  `pipeline/graph_store.py`), `graph/normalize.py` (vorher
  `pipeline/normalize.py`), `graph/ask.py`-Logik (vorher `ask.py`,
  `select_nodes`/`collect_edges`/`format_triple`/`build_subgraph`
  unveraendert), Prompts `ask_select.md`/`ask_answer.md`/`normalize_judge.md`.
- Neu: `GraphStore.to_json()`/`from_json()` fuer die API; `ask()` gibt jetzt
  ein Dict zurueck statt zu drucken/HTML zu schreiben.
- FastAPI-App (`app.py`) mit `/health`, `/graph`, `/triples`, `/ask`.
- Frontend (`static/index.html` + `app.js`, vis-network lokal vendored,
  kein CDN): eine Seite, Fragen ohne Reload, Graph wird direkt aus der
  JSON-Antwort gezeichnet (ersetzt die vorherigen von `visualize.py`
  statisch erzeugten HTML-Dateien).
- `polygraph` schickt Rohtripel jetzt per `POST /triples` hierher, statt
  lokal zu normalisieren/speichern (siehe polygraph/PROGRESS.md).

**Architektur-Review: 3 Wachstums-/Mehrbenutzer-Risiken behoben (fertig)**
- **Duplikate statt Aktualisierung**: `GraphStore.add_triple` (`graph/store.py`)
  legte bei jedem Aufruf eine neue parallele Kante an, auch wenn zwischen
  denselben Knoten mit derselben Relation schon eine existierte - bei
  wiederholter Ingestion (gleicher Text zweimal, ueberlappende Dokumente)
  waeren unbegrenzt Duplikate entstanden. Jetzt sucht `_find_edge_key` eine
  bestehende Kante mit gleicher Relation und aktualisiert sie, statt eine
  neue anzulegen. Isoliert getestet: identisches Tripel dedupliziert, gleiche
  Relation mit neuem `value` aktualisiert in-place, andere Relation legt
  korrekt eine zweite Kante an.
- **Normalisierung unvektorisiert**: Kandidatensuche verglich jeden neuen
  Begriff per reiner Python-Schleife (`sum()`/`sqrt()`) gegen ALLE bekannten
  Begriffe - O(N) Pythonschleifen pro Tripel-Feld, bei wachsendem Graphen
  spuerbar langsam. `graph/normalize.py::_top_matches` macht das jetzt als
  eine NumPy Matrix-Vektor-Multiplikation. Verschiebt die Schmerzgrenze um
  Groessenordnungen, das grundsaetzliche O(N)-Wachstum bleibt aber (siehe
  offene Punkte).
- **Keine Nebenlaeufigkeitssicherung**: FastAPI fuehrt synchrone Routen im
  Thread-Pool aus; zwei gleichzeitige `POST /triples` haetten denselben
  NetworkX-Graphen aus zwei Threads gleichzeitig mutieren koennen (von
  NetworkX nicht abgesichert). `app.py::store_lock` serialisiert jetzt
  jeden Zugriff. Mit 10 parallelen Requests getestet (ThreadPoolExecutor):
  Knoten-/Kantenzahl stimmt exakt, kein Datenverlust, kein Fehler.

## Offene Punkte

1. Noch nicht gebaut: mehrere Service-Instanzen (z.B. Kollegen-Graph) von
   einer Oberflaeche gemeinsam abfragen. API ist dafuer ausgelegt
   (`/graph`- und `/ask`-Antwortformat generisch), fehlt nur im Frontend.
2. Kein Auth/Zugriffsschutz - bisher nur fuer lokalen Gebrauch gedacht.
3. Bei sehr grossem Graphen wird `GET /graph` (kompletter Graph als JSON)
   und die Kraft-Layout-Physik im Frontend langsam; dann eher serverseitig
   filtern/paginieren statt immer alles zu laden.
4. **Embedding-Cache-Grenze**: `graph/normalize.py::_embed` cached per
   `@lru_cache(maxsize=4096)` im Prozessspeicher. Ab mehr als 4096
   unterschiedlichen Begriffen werden aeltere verdraengt und muessen erneut
   ueber Ollama embedded werden - Normalisierung wird dann unvorhersehbar
   langsamer. Noch nicht behoben (aus dem Architektur-Review bewusst
   zurueckgestellt); Fix waere, Embeddings als Knoten-Attribut im Graphen
   selbst zu persistieren statt im Prozess-Cache.
5. **Nicht-atomares Speichern**: `GraphStore.save` (`graph/store.py`)
   schreibt `data/graph.gml` direkt an ihrem Zielpfad; ein Absturz mitten im
   Schreiben wuerde die Datei beschaedigen. Noch nicht behoben; Fix waere
   Schreiben in eine temporaere Datei + `os.replace`.
6. Kein automatisierter Test fuer den API-Vertrag (`/health`, `/graph`,
   `/triples`, `/ask`) - Schema-Drift zwischen dieser Instanz und der eines
   Kollegen wuerde erst beim gemeinsamen Betrieb auffallen.

## Naechste Ausbaustufen

- Umstieg von NetworkX auf Neo4j, falls der Graph wirklich gross wird
  (nur `graph/store.py` betroffen)
