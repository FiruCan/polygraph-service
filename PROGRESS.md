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

## Offene Punkte

1. Noch nicht gebaut: mehrere Service-Instanzen (z.B. Kollegen-Graph) von
   einer Oberflaeche gemeinsam abfragen. API ist dafuer ausgelegt
   (`/graph`- und `/ask`-Antwortformat generisch), fehlt nur im Frontend.
2. Kein Auth/Zugriffsschutz - bisher nur fuer lokalen Gebrauch gedacht.
3. Bei sehr grossem Graphen wird `GET /graph` (kompletter Graph als JSON)
   und die Kraft-Layout-Physik im Frontend langsam; dann eher serverseitig
   filtern/paginieren statt immer alles zu laden.

## Naechste Ausbaustufen

- Umstieg von NetworkX auf Neo4j, falls der Graph wirklich gross wird
  (nur `graph/store.py` betroffen)
