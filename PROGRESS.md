# Progress

## Stand

**Kandidaten-Verdraengung bei der Normalisierung behoben + atomares Speichern (fertig)**
- Grund: "MS" und "Multiple Sklerose" blieben trotz Normalisierung als
  zwei getrennte Knoten im Graphen stehen - obwohl `find_match('MS', ...)`
  in einem kleinen Test isoliert korrekt funktionierte.
- Ursache gefunden am echten, gewachsenen Graphen (340 Knoten): die
  Kandidatensuche schnitt zuerst auf `MAX_CANDIDATES=5` ab und filterte
  danach nach Schwellenwert. "Multiple Sklerose" hatte einen validen Score
  (0.587, über der Schwelle 0.55), landete aber auf Rang 13 - verdraengt
  von 12 Begriffen, die "MS" als Textbaustein enthalten ("MS-Risikogene",
  "progrediente MS", "MS-Schuebe", ...) und dadurch hoeher scoren, obwohl
  sie NICHT dieselbe Entitaet sind. Der echte Treffer erreichte den LLM-
  Richter also nie.
- `find_match` filtert jetzt ERST nach Schwellenwert, DANACH erst auf
  `MAX_JUDGE_CANDIDATES` (auf 20 erhoeht) begrenzt - nicht umgekehrt.
  Verifiziert direkt am echten Graphen: `find_match('MS', ...)` findet
  jetzt korrekt "Multiple Sklerose". Regressionsgetestet: "IL-8"/"IL-15",
  "IL-8"/"Interleukin-6", "Typ-I-"/"Typ-II-Diabetes" verschmelzen weiterhin
  nicht faelschlich.
- **Waehrend der manuellen Reparatur des bestehenden "MS"-Knotens im Graphen
  ist ein echter Datenverlust passiert**: `GraphStore.save()` schrieb bisher
  direkt auf `data/graph.gml`; ein nicht-serialisierbarer Wert (None) liess
  `nx.write_gml` mitten im Schreiben abstuerzen und eine abgeschnittene,
  kaputte Datei zuruecklassen (nur 37 von 340 Knoten, 0 Kanten). Kein
  Backup vorhanden, Graph musste aus den Originalquellen neu aufgebaut
  werden (technisch vollstaendig, aber vermeidbarer Zeitverlust).
  `save()` schreibt jetzt in eine temporaere Datei und benennt sie erst
  danach atomar um (`os.replace`) - ein Absturz mitten im Schreiben kann
  die vorherige gueltige Datei nicht mehr zerstoeren.
- Zugrunde liegende Ursache des Absturzes ebenfalls behoben:
  `add_triple` ueberschrieb den Typ eines bereits bekannten Knotens
  bedingungslos, auch mit `None`, wenn ein spaeteres Tripel keinen Typ
  mitgab. `_add_or_update_node` aktualisiert den Typ jetzt nur, wenn ein
  echter (nicht-None) Wert vorliegt.

**Gekennzeichnete Ableitung bei Fragen, die ueber den Graphen hinausgehen (fertig)**
- Grund: Frage "Wenn ein MS-Patient eine Nacht schlecht schlaeft, wie
  wirkt sich das auf seine Fatigue aus?" wurde trotz vorhandener,
  thematisch naher Fakten (Fatigue ist Symptom von MS) immer mit "Das
  steht nicht im Graphen" beantwortet - obwohl eine vorsichtige Ableitung
  aus Graph-Fakt + Fachwissen moeglich gewesen waere.
- Ursache gefunden durch isolierten Test mit `think=True`: das Modell
  KONNTE die Ableitung korrekt herleiten, sobald es einen Denkschritt
  bekam. `graph/ask.py::_chat` rief die Antwort-Generierung bisher aber
  immer mit `think=False` auf - ohne Denkschritt fiel das Modell
  reflexhaft auf die sichere Ablehnung zurueck.
- `prompts/ask_answer.md` erlaubt jetzt zwei klar getrennte Aussagearten:
  "BELEGTE FAKTEN" (wie bisher, mit Tripel-Nummer als Beleg) und
  "Vermutung (nicht im Graphen belegt):" als eigener, deutlich markierter
  Abschnitt - nur wenn eine plausible Ableitung aus vorhandenen Fakten +
  etabliertem Fachwissen moeglich ist, keine erfundenen Zahlen/Studien.
- `graph/ask.py::ask()` ruft die Antwort jetzt mit `think=True` und
  `num_predict=6000` auf (select_nodes bleibt bei `think=False` - einfache
  Auswahlaufgabe, kein Denkschritt noetig).
- Getestet: MS/Schlaf-Frage liefert jetzt "BELEGTE FAKTEN: ... [21]" plus
  "Vermutung (nicht im Graphen belegt): Schlechter Schlaf... kann die
  Fatigue... voraussichtlich verstaerken." Regressionsgetestet, dass die
  Sicherheit erhalten bleibt: eine unsinnige Frage (Apple-Aktienkurs vs.
  MS-Fatigue) bekommt weiterhin "Das steht nicht im Graphen" ohne
  erzwungene Ableitung.

**Quellenbasiertes Ersetzen bei erneutem Import (fertig)**
- Grund: Re-Importieren derselben Quelle (Extraktion ist nicht
  deterministisch, siehe polygraph/PROGRESS.md) liess pro Lauf zwischen 0
  und N neue Knoten/Kanten entstehen, weil `add_triple`s Dedup nur exakt
  identische (Subjekt, Objekt, Relation) erkennt - eine leicht anders
  formulierte, aber inhaltlich gleiche Aussage aus demselben Artikel wurde
  einfach zusaetzlich eingefuegt statt die veraltete Version zu ersetzen.
- Jede Kante bekommt jetzt optional ein `source`-Feld (z.B. die Artikel-URL
  oder der Dateipfad). `POST /triples` mit `source` im Body loescht zuerst
  ALLE Kanten mit genau diesem `source`-Wert (`GraphStore.remove_edges_by_
  source`, entfernt danach auch verwaiste Knoten) und fuegt erst dann die
  neuen Tripel ein - so bleibt ein erneuter Import derselben Quelle
  idempotent, egal wie stark sich die Extraktion im Detail unterscheidet.
- `source` steht bewusst an der KANTE, nicht am Knoten: ein Knoten wie
  "Muskeln" kann aus vielen Quellen stammen, eine einzelne Aussage
  ("sekretiert IL-6") stammt aus genau einer.
- `_find_edge_key` dedupliziert jetzt nur noch innerhalb derselben Quelle
  (gleiche Relation UND gleicher `source`). Behauptet eine ANDERE Quelle
  (oder Tripel ohne `source`) dieselbe Relation zwischen denselben Knoten,
  bleibt das eine eigene Kante - keine Duplizierung, sondern zwei
  unabhaengige Belegstellen fuer dieselbe Aussage.
- Getestet (ueber `polygraph/build_graph.py --source ...`): 1. Import mit
  Quelle X -> 0 entfernt (korrekt, erster Import). 2. und 3. Import
  derselben Datei mit derselben Quelle X -> jeweils exakt dieselben 19
  Kanten/2 Knoten vorher entfernt, Graph bleibt stabil bei 122/147 -
  idempotent bei wiederholtem Import bestaetigt.
- Bekannte Einschraenkung: Kanten aus Importen VOR dieser Aenderung haben
  kein `source`-Feld und werden beim erneuten Import derselben Quelle nicht
  rueckwirkend erkannt/entfernt (bewusst so - lieber nichts faelschlich
  loeschen als raten). Ab jetzt getaggte Importe funktionieren korrekt.

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
