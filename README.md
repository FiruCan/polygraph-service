# polygraph-service

Haelt einen Wissensgraphen (NetworkX, persistiert als `data/graph.gml`) und
bietet ihn per HTTP an: Tripel einspeisen, Fragen stellen (GraphRAG, lokales
Ollama), Graph abrufen. Reine API ohne eigene Oberflaeche - die
Weboberflaeche liegt im Projekt [polygraph](../polygraph) (`kg/`, Port 8001).

Gedacht als **eigenstaendiger Service pro Person/Domain**: Wer einen eigenen
Wissensgraphen aufbaut (z.B. eine andere Domain), betreibt eine eigene
Instanz dieses Projekts. Die API unten ist der Vertrag dafuer - zwei
kompatible Instanzen liefern Graph/Antworten im selben JSON-Format, sodass
sich beide von einer gemeinsamen Oberflaeche aus abfragen lassen, ohne die
Graphen selbst zu vermischen.

**Keine feste Domain:** welches Fachgebiet ein Graph hat, bestimmen die
Artikel, die importiert werden. Pro Thema laeuft eine eigene Instanz. Das
Vokabular (Knotentypen, Relationen) waechst aus den Tripeln;
`GET /vocabulary` liefert es polygraph fuer die Extraktion, und die
haeufigsten Knotentypen sagen den Prompts, worum es geht (z.B. ob
"Bewegung" "physical activity" oder "motion" heisst).

Tripel kommen von aussen (z.B. aus dem separaten
[polygraph](https://github.com/FiruCan/polygraph)-Projekt, das Text per
lokalem LLM in Tripel extrahiert) und werden hier normalisiert und
gespeichert.

**Sprache:** Alles im Graphen ist **Englisch** - Knotennamen, die
Angaben an den Kanten (`value`, `condition`, `evidence_level`) und die
Knotentypen; beim Import wird uebersetzt (`graph/translate.py`). Fragen,
Antworten, Vorschlaege und Erklaerungen gibt es in einer frei waehlbaren
Sprache (`language`, z.B. `"Deutsch"`, `"Englisch"`, `"Tuerkisch"`;
Standard `"Deutsch"`). Relationen kommen schon englisch aus polygraph und
werden nicht uebersetzt.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

ollama pull gemma4:26b   # Fragen + Normalisierungs-Entscheidung
ollama pull bge-m3       # Normalisierungs-Kandidatensuche (Embeddings)
```

## Starten

```bash
uvicorn app:app --reload --port 8000
```

Der Graph wird in `data/graph.gml` persistiert und beim Start automatisch
geladen, falls vorhanden. Ansehen und befragen: Oberflaeche von polygraph
starten (`uvicorn ingest_app:app --port 8001` dort) und
`http://localhost:8001` oeffnen.

Die Oberflaeche ruft diesen Service per HTTP von einem anderen Port aus auf;
der Service erlaubt das per CORS standardmaessig fuer jede Seite von
localhost/127.0.0.1. Fuer andere Rechner `POLYGRAPH_CORS_ORIGIN_REGEX`
setzen.

## Tests

```bash
python3 -m pytest test -q
```

`test_store.py`, `test_normalize.py`, `test_app.py` mocken Ollama und
schreiben nie in `data/graph.gml` (App-Tests nutzen eine temporaere Datei).
`test_normalize_judge_live.py` prueft den LLM-Richter gegen echtes Ollama
(wird uebersprungen, wenn Ollama nicht laeuft) - nach jeder Aenderung an
`prompts/normalize_judge.md` laufen lassen.

## API

Uebersicht aller Endpoints im Browser: `http://localhost:8000/help` (leitet
auf die automatische API-Doku `/docs` weiter).

Tripel-Schema (wie von einer Extraktions-Pipeline erzeugt, z.B. `polygraph`):

```json
{
  "subject": "Krafttraining", "subject_type": "lifestyle_factor", "subject_type_is_new": false,
  "relation": "reduces_risk_of", "relation_is_new": false,
  "object": "Herz-Kreislauf-Erkrankungen", "object_type": "disease", "object_type_is_new": false,
  "value": "15 bis 20 Prozent", "condition": "1-2 Einheiten pro Woche",
  "evidence_level": "Beobachtungsstudie", "confidence": 0.9
}
```

- `GET /health` -> `{"status": "ok", "nodes": N, "edges": M}`
- `GET /graph` -> `{"nodes": [{"id": str, "type": str|null}], "edges": [{"source": str, "target": str, "relation": str, "value": ..., "condition": ..., "evidence_level": ..., "confidence": ...}]}`
- `POST /triples` Body `{"triples": [<Tripel>, ...]}` -> normalisiert jedes
  Tripel gegen den aktuellen Graphen und fuegt es ein. Antwort:
  `{"added": N, "merges": [["subject"|"object"|"relation", "alt", "neu"], ...], "nodes": N, "edges": M}`
- `POST /ask` Body `{"question": str, "language": "Deutsch"}` -> GraphRAG: waehlt passende Knoten,
  holt deren Kanten (bis 2 Hops), ein Agent antwortet nur anhand dieser
  Tripel und darf bei Bedarf per Werkzeug (Knotensuche, Kanten eines
  Knotens, Pfad zwischen zwei Knoten) weitere Tripel nachladen.
  Antwort:
  `{"question": str, "selected_nodes": [str], "answer": str, "triples": [{"n": 1, "subject": ..., "relation": ..., "object": ..., "value": ..., "condition": ..., "evidence_level": ..., "confidence": ...}], "graph": {"nodes": [...], "edges": [...]}, "steps": [{"tool": str, "args": {...}, "new_triples": int}], "glossary": [{"term": str, "type": str, "explanation": str | null}], "pruefung": {"status": "geprueft"|"ungeprueft", "saetze": [{"satz": str, "urteil": "gedeckt"|"teilweise"|"nicht_gedeckt"|"vermutung"|"keine_aussage", "belege": [int], "begruendung": str}], "dauer_s": float}}`
  `pruefung`: Antwort-Pruefer - jeder Satz gegen die zitierten Tripel
  geprueft; die Antwort selbst bleibt unveraendert, die Oberflaeche markiert
  nicht gedeckte Saetze.
  `graph` ist der verwendete Teilgraph, im selben Format wie `GET /graph` -
  dieselbe Frontend-Logik zeichnet beides.
- `GET /questions/suggest?count=5&language=Deutsch` (count 1-10) -> `{"questions": [{"question": str, "type": "detail"|"knoten"|"pfad"|"vergleich", "nodes": [str]}]}`
  - Beispielfragen aus dem Graphen, reihum vier Arten: Kanten mit
  Bedingung/Wert/Evidenz, vernetzte Knoten, Pfade ueber 2-4 Schritte, zwei
  Knoten mit demselben Ziel. Ein LLM-Aufruf formuliert sie detailreich;
  jede Frage entsteht aus echten Kanten, ist also beantwortbar. Zuletzt
  benutzte Ausgangspunkte (300, im Speicher) werden ausgelassen - keine
  Wiederholungen, bis alles einmal dran war. In der Oberflaeche: Button
  "Fragen vorschlagen", Klick auf einen Vorschlag stellt die Frage.
- `GET /vocabulary` -> `{"types": [{"name": str, "count": int}], "relations": [{"name": str, "count": int}], "type_parents": {typ: obertyp}}`
  - Knotentypen und Relationen mit Haeufigkeit, haeufigste zuerst.
  polygraph gibt die haeufigen der Extraktion als bekanntes Vokabular mit.
  `type_parents` ist die Typ-Hierarchie (`"disease": "condition"`), auch
  fuer Typen ohne Knoten (die Wurzeln aus polygraphs Startvokabular).
- `POST /vocabulary/parents` Body `{"parents": {typ: obertyp | null}}` ->
  `{"changed": N, "type_parents": M}` - setzt Obertypen, `null` entfernt
  einen (Vokabular-Steward, nach Freigabe). Ein Kreis
  (`cell` -> `immune_cell` -> `cell`) wird mit 400 abgelehnt, dann aendert
  sich nichts. Gespeichert in `data/graph.hierarchy.json` neben dem Graphen,
  nicht als Knoten - Typen tauchen so nicht in `/graph`, Antworten oder
  Fragevorschlaegen auf.
- `POST /entities/similar` Body `{"names": [str], "limit": 3}` ->
  `{"matches": {name: [aehnliche bekannte Knoten]}}` - Embedding-Aehnlichkeit
  ohne LLM, fuer Entity-Linking in polygraph vor der Extraktion. Namen, die
  schon im Graphen stehen, bekommen keine Hinweise.
- `POST /vocabulary/rename` Body `{"kind": "relation"|"type", "old": str, "new": str}`
  -> `{"changed": N, ...}` - benennt eine Relation bzw. einen Knotentyp im
  ganzen Graphen um (Vokabular-Steward in polygraph, nach Freigabe durch
  einen Menschen). Bei Typen zieht die Typ-Hierarchie mit; gibt es den
  neuen Typ schon, behaelt er seinen Obertyp.

- `POST /explain` Body `{"term": str, ..., "language": "Deutsch"}` ->
  ausfuehrliche Erklaerung eines Begriffs in der gewaehlten Sprache.
- `POST /nodes/rename` Body `{"renames": [{"old": str, "new": str}, ...]}`
  -> `{"renamed": N, "merged": N, "skipped": [...], ...}` - benennt Knoten
  um; existiert der neue Name schon, werden beide zusammengefuehrt.
  Speichert einmal am Ende.
- `POST /edges/rewrite` Body `{"rewrites": [{"field": "value"|"condition"|"evidence_level", "old": str, "new": str}, ...]}`
  -> `{"changed": N}` - ersetzt eine Angabe auf allen Kanten.
- `POST /duplicates/find` Body `{"threshold": 0.75, "limit": null}` ->
  `{"vorschlaege": [{"behalten": str, "entfernen": str, "begruendung": str, "schritte": [str], "beleg": "schreibweise"|"abkuerzung"|null, "mehrdeutig": [str], "aehnlichkeit": float, "kanten": {...}, "typen": {...}, "freigegeben": bool}], "richter_aufrufe": int, "llm_aufrufe": int, "knoten": int, "dauer_s": float}`
  - Duplikat-Aufraeumer: doppelte Knoten im ganzen Graphen (Embedding und
  Namen liefern Kandidaten, ein Richter-Agent urteilt und kann per
  `suche_knoten` z.B. die Langform einer Abkuerzung nachschlagen -
  `schritte` zeigt die Suchen), aendert nichts. `freigegeben` ist ein
  Vorschlag nur, wenn auch die Namen ihn belegen (`beleg`) und eine
  Abkuerzung eindeutig ist (sonst `mehrdeutig`: gleichauf liegende
  Langformen). Dauert lange (~1 Std. bei ~3.000 Knoten); `limit` begrenzt
  die Richter-Aufrufe fuer Probelaeufe. Aufruf ueber polygraph `dedupe.py`
  (`--auto`: vollautomatisch).
- `POST /nodes/merge` Body `{"keep": str, "remove": str}` ->
  `{"moved": n, "collapsed": n, "dropped_self_loops": n, "nodes": N, "edges": M}`
  - Kanten von `remove` an `keep` umhaengen, `remove` loeschen (nach
  Freigabe durch den Duplikat-Agenten oder einen Menschen). 404 wenn ein
  Knoten fehlt.
- `POST /graph/backup` -> `{"backup": "graph.backup-<Zeitstempel>.gml"}` -
  Kopie von `data/graph.gml` und, falls vorhanden, der Typ-Hierarchie als
  `graph.backup-<Zeitstempel>.hierarchy.json` (ruft polygraph
  `dedupe.py --auto` vor dem Zusammenfuehren auf). Zurueckholen: Service
  stoppen, beide Dateien zurueckkopieren, Service starten.

## Bestand auf Englisch umstellen

Einmalig, bei laufendem Service mit dem neuen Code (~1 Std. fuer 2.800
Knoten und ~1.700 Kanten-Angaben):

```bash
python3 translate_graph.py plan
```

schreibt `data/translate_review.json` mit drei Listen: `knoten` (alt ->
neu, `zusammenfuehren`, `freigegeben`), `kanten` (`feld`, alt -> neu,
`freigegeben`) und `typen` (wie `knoten`, umbenannt ueber
`POST /vocabulary/rename`). Mit `--nur typen` (bzw. `knoten`, `kanten`)
wird nur ein Teil geprueft. Durchsehen, falsche Eintraege korrigieren oder
auf `"freigegeben": false` setzen, dann:

```bash
python3 translate_graph.py apply
```

legt vorher `data/graph.backup-<Zeitstempel>.gml` an.

## Projektstruktur

```
polygraph-service/
├── app.py              # FastAPI-Routen (health, graph, triples, ask, ...), reine API
├── graph/
│   ├── store.py        # NetworkX-Wrapper, to_json()/from_json() fuer die API
│   ├── normalize.py    # Synonyme zusammenfuehren (bge-m3-Embedding + gemma4:26b-Pruefung)
│   ├── translate.py    # Knotennamen, Kanten-Angaben + Typen ins Englische (gemma4:26b, paketweise, gecacht)
│   └── ask.py           # GraphRAG: Knoten waehlen -> Kanten holen -> Agent antwortet (laedt bei Bedarf nach)
├── prompts/             # ask_select.md, ask_answer.md, normalize_judge.md
├── translate_graph.py   # einmalige Umstellung des Bestands auf Englisch
├── test/                # Unit-Tests + Live-Test fuer den Normalisierungs-Richter
└── data/graph.gml       # persistierter Graph (git-ignoriert)
```

## Naechste Ausbaustufen

- Umstieg von NetworkX auf Neo4j, falls der Graph wirklich gross wird
  (nur `graph/store.py` betroffen, Rest bleibt gleich)
- Mehrere Graphen gleichzeitig von einer Oberflaeche abfragen (z.B. eigener
  und der eines Kollegen): braucht nur eine Frontend-Erweiterung, die
  mehrere Service-URLs abfragt und die `graph`-Antworten kombiniert - die
  API ist dafuer bereits generisch genug.
