# polygraph-service

Haelt einen Wissensgraphen (NetworkX, persistiert als `data/graph.gml`) und
bietet ihn per HTTP an: Tripel einspeisen, Fragen stellen (GraphRAG, lokales
Ollama), Graph in einer Weboberflaeche ansehen.

Gedacht als **eigenstaendiger Service pro Person/Domain**: Wer einen eigenen
Wissensgraphen aufbaut (z.B. eine andere Domain), betreibt eine eigene
Instanz dieses Projekts. Die API unten ist der Vertrag dafuer - zwei
kompatible Instanzen liefern Graph/Antworten im selben JSON-Format, sodass
sich beide von einer gemeinsamen Oberflaeche aus abfragen lassen, ohne die
Graphen selbst zu vermischen.

Tripel kommen von aussen (z.B. aus dem separaten
[polygraph](https://github.com/FiruCan/polygraph)-Projekt, das Text per
lokalem LLM in Tripel extrahiert) und werden hier normalisiert und
gespeichert.

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

Danach `http://localhost:8000` im Browser oeffnen (Frontend: Graph ansehen,
Fragen stellen). Der Graph wird in `data/graph.gml` persistiert und beim
Start automatisch geladen, falls vorhanden.

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
- `POST /ask` Body `{"question": str}` -> GraphRAG: waehlt passende Knoten,
  holt deren Kanten (bis 2 Hops), das LLM antwortet nur anhand dieser Tripel.
  Antwort:
  `{"question": str, "selected_nodes": [str], "answer": str, "triples": [{"n": 1, "subject": ..., "relation": ..., "object": ..., "value": ..., "condition": ..., "evidence_level": ..., "confidence": ...}], "graph": {"nodes": [...], "edges": [...]}}`
  `graph` ist der verwendete Teilgraph, im selben Format wie `GET /graph` -
  dieselbe Frontend-Logik zeichnet beides.

## Projektstruktur

```
polygraph-service/
├── app.py              # FastAPI-Routen (health, graph, triples, ask), serviert static/
├── graph/
│   ├── store.py        # NetworkX-Wrapper, to_json()/from_json() fuer die API
│   ├── normalize.py    # Synonyme zusammenfuehren (bge-m3-Embedding + gemma4:26b-Pruefung)
│   └── ask.py           # GraphRAG: Knoten waehlen -> Kanten holen -> LLM antwortet mit Belegen
├── prompts/             # ask_select.md, ask_answer.md, normalize_judge.md
├── test/                # Unit-Tests + Live-Test fuer den Normalisierungs-Richter
├── static/              # index.html + app.js (vis-network), eine dynamische Seite ohne Reload
└── data/graph.gml       # persistierter Graph (git-ignoriert)
```

## Naechste Ausbaustufen

- Umstieg von NetworkX auf Neo4j, falls der Graph wirklich gross wird
  (nur `graph/store.py` betroffen, Rest bleibt gleich)
- Mehrere Graphen gleichzeitig von einer Oberflaeche abfragen (z.B. eigener
  und der eines Kollegen): braucht nur eine Frontend-Erweiterung, die
  mehrere Service-URLs abfragt und die `graph`-Antworten kombiniert - die
  API ist dafuer bereits generisch genug.
