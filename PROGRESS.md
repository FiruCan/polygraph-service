# Progress

## Stand

**Fragen vorschlagen (fertig, noch nicht im Browser getestet)**
- Grund: man soll sich nicht selbst Fragen an den Graphen ausdenken muessen.
- `graph/suggest.py` + `prompts/suggest_questions.md`, `GET /questions/suggest`:
  Ausgangspunkte aus der Graph-Struktur ohne LLM (stark vernetzte Knoten;
  Knotenpaare mit 2-4 Schritten Abstand), dann EIN LLM-Aufruf, der pro
  Ausgangspunkt eine Frage formuliert - mit den zugehoerigen Fakten im
  Prompt. Jede Frage entsteht aus echten Kanten und ist damit beantwortbar.
  Zufaellige Auswahl, damit jeder Klick neue Vorschlaege bringt. Scheitert
  der LLM-Aufruf, kommen Fragen aus einer festen Vorlage.
- Bewusst KEIN Agent (keine Werkzeug-Schleife): die Struktur liefert der
  Graph-Algorithmus exakt und sofort, das LLM wird nur zum Formulieren
  gebraucht - ein Aufruf (~10-20 s) statt mehrerer Runden.
- Arbeitet auf einer Kopie des Graphen, damit ein gleichzeitiger Import
  nicht auf den LLM-Aufruf warten muss.
- Frontend: Button "Fragen vorschlagen", Vorschlaege als Buttons, Klick
  stellt die Frage ueber den bestehenden Antwort-Agenten.
- Tests: `test/test_suggest.py`, `test_app.py`.

**Endpunkte fuer Entity-Linking und Vokabular-Steward (fertig)**
- Grund: zwei neue Agenten in polygraph brauchen Zugriff auf den Graphen.
- `POST /entities/similar` (`normalize.py::similar_entities`): pro Name die
  bis zu 3 aehnlichsten bekannten Knoten per bge-m3-Embedding, ohne LLM
  (schnell). Schwelle 0.6 statt 0.75: das Embedding erkennt Abkuerzungen
  schlecht ("IL6": IL-8 0.67, Interleukin-6 0.64) - ob ein Hinweis
  dieselbe Sache ist, entscheidet das Extraktionsmodell in polygraph.
  Namen, die schon (auch in anderer Schreibung) im Graphen stehen, bekommen
  keine Hinweise ("Muskelzellen" bekam sonst "Muskeln").
- `POST /vocabulary/rename` (`store.py::rename_relation/retype_nodes`):
  Relation/Knotentyp im ganzen Graphen umbenennen, speichert nur bei
  Aenderungen; entfernt `relation_is_new` an umbenannten Kanten.
- Offen: nach einer Umbenennung koennen zwei Kanten mit gleicher Relation
  und gleicher Quelle zwischen denselben Knoten entstehen - werden nicht
  zusammengelegt.
- Tests in `test_store.py`, `test_normalize.py`, `test_app.py`.

**Frontend: Service-URL umschaltbar (fertig)**
- Grund: eigenes Frontend soll auch die Kollegen-Instanz bedienen koennen -
  nacheinander, nicht gleichzeitig (gleichzeitig = offener Punkt 1).
- `static/index.html`/`app.js`: Feld "Service-URL" + "Verbinden" oben in
  der Seitenleiste; `/graph` und `/ask` gehen an diese URL (leer = eigener
  Server). Wird in localStorage gemerkt. Nicht erreichbarer Service ->
  Hinweis in der Statuszeile statt stillem Fehler.
- `app.py`: CORS-Middleware, sonst blockiert der Browser die Anfrage an
  einen anderen Port. Standard: localhost/127.0.0.1 beliebiger Port,
  anderes per `POLYGRAPH_CORS_ORIGIN_REGEX`.
- Daten fremder Instanzen werden vor `innerHTML` escaped (Belege, Quelle,
  Legende).
- Getestet: 2 CORS-Tests in `test_app.py`; im Browser Frontend auf 8010
  -> Kollegen-Testinstanz auf 8011 (Graph geladen), nicht erreichbare URL
  (Hinweis), zurueck auf leer (eigener Graph).
- Hinweis Ports: 8000 = eigener Service, 8001 ist lokal schon von
  `ingest_app` belegt - Kollegen-Instanz z.B. auf 8002.

**Frage-Agent: Antwortgeber darf Tripel nachladen (fertig)**
- Grund: `ask()` war eine feste Pipeline - Knoten waehlen, 2 Hops holen,
  einmal antworten. Fehlte die passende Kante im Ausschnitt (Startknoten
  verfehlt, Kette laenger als 2 Hops), konnte das Modell nicht nachfassen.
  `store.py` hatte `neighbors`/`shortest_path` dafuer, ungenutzt.
- `graph/ask.py::_agent_answer`: Antwortgeber bekommt die bisherigen
  Start-Tripel und drei Werkzeuge (Ollama Tool Calling, gemma4:26b kann
  das): `suche_knoten` (Teilstring), `kanten_von`, `pfad`. Max.
  `MAX_TOOL_ROUNDS=4` Runden, danach eine letzte Runde ohne Werkzeuge.
  Grenzen: 40 Tripel pro Aufruf, 250 insgesamt.
- Belege bleiben eindeutig: `_Evidence` vergibt jeder Kante genau eine
  Nummer; nachgeladene Tripel werden weiternummeriert, schon bekannte
  behalten ihre Nummer.
- Agent laeuft auch ohne Startknoten (findet Einstieg selbst per
  `suche_knoten`) - vorher kam dann sofort "Kein passender Knoten".
- API: `/ask` liefert zusaetzlich `steps` (Werkzeugaufrufe);
  `selected_nodes` enthaelt jetzt auch die vom Agenten untersuchten
  Knoten, aber nur solche im Teilgraphen (sonst Absturz im Frontend, das
  sie als Startpunkte zeichnet). Bestehende Felder unveraendert.
- `prompts/ask_answer.md`: neuer Abschnitt WERKZEUGE (erst nachladen,
  wenn Tripel nicht reichen; nicht doppelt aufrufen).
- Tests: `test/test_ask.py` (7, Ollama gemockt). Live am echten Graphen:
  Fragen mit ausreichendem Ausschnitt -> 0 Werkzeugaufrufe, ~20 s wie
  bisher. Mit absichtlich schwacher Startauswahl (HOPS=1) holte der Agent
  per `pfad`/`kanten_von` die Kette Krafttraining -> Muskeln -> IL-6 ->
  Entzuendungen selbst (4 Aufrufe, 82 s). Unsinnsfrage (Apple-Aktie):
  4 erfolglose Suchen, dann weiterhin "Das steht nicht im Graphen."
- Kosten: Unsinnsfragen dauern jetzt laenger (Agent sucht erst, ~18 s
  statt sofortiger Absage); jede Werkzeug-Runde ist ein weiterer
  LLM-Aufruf mit Denkschritt.

**Tests + Normalisierungs-Richter verlaesslicher (fertig)**
- Grund: der Service hatte keine Tests; beim Neuaufbau des Graphen
  (2026-10-08) fuehrte die Normalisierung "Glukose" mit "Blutzucker"
  zusammen und entschied "Skelettmuskel" je nach Kandidatenliste
  unterschiedlich.
- `test/`: `test_store.py`, `test_normalize.py`, `test_app.py` (Ollama
  gemockt, 100%/97% Coverage auf app/normalize/store) und
  `test_normalize_judge_live.py` (25 Begriffspaare gegen echtes Ollama,
  beide Richtungen: Synonyme MUESSEN, verwandte Begriffe DUERFEN NICHT
  zusammengefuehrt werden; Kontrollgruppen stehen nicht im Prompt).
- Bug gefunden und behoben: ein Tripel ohne subject_type/object_type legte
  einen Knoten mit type=None an, write_gml scheiterte daran - und weil das
  Tripel im Speicher blieb, scheiterte danach JEDES save() bis zum
  Neustart. `store.py` setzt unbekannte Typen jetzt gar nicht erst.
- `normalize_judge.md`: neue Regel "Stoff und sein Messwert im Blut sind
  nicht dasselbe" (Glukose/Blutzucker). Eine erste, laengere Fassung machte
  den Richter so vorsichtig, dass er echte Synonyme ablehnte - der
  Live-Test prueft deshalb beide Richtungen.
- `normalize.py::_judge`: Structured Output mit erst "begruendung", dann
  "treffer" (enum: nur Kandidaten oder null). Ohne Begruendung waehlte das
  Modell bei vielen aehnlichen Kandidaten den aehnlichsten statt zu pruefen,
  ob er dasselbe ist ("Skelettmuskel": 2 Kandidaten -> korrekt abgelehnt,
  9 Kandidaten aus dem echten Graphen -> "Muskeln"). Jetzt 25/25 im
  Live-Test, aber ca. 1.3 s statt 0.5 s pro Entscheidung.

**Quellenangabe (origin) im Frontend sichtbar (fertig)**
- `origin` stand schon in `GraphStore.to_json()`, wurde aber nirgends
  angezeigt. `graph/ask.py::ask()` gibt jetzt `origin` pro Tripel in der
  API-Antwort mit. `static/app.js`: Kanten-Tooltip im Graphen zeigt jetzt
  "Quelle: ..."; die Beleg-Liste bei Antworten zeigt die Quelle unter
  jedem zitierten Tripel (eigene, dezente Zeile).

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

1. Noch nicht gebaut: mehrere Service-Instanzen GLEICHZEITIG von einer
   Oberflaeche abfragen (Umschalten per Service-URL geht schon). API und
   CORS sind dafuer bereit, fehlt nur im Frontend.
2. **Freigabe an Kollegen (Netzwerk + Zugriffsschutz)**: Ziel ist, dass der
   Kollege in SEINEM Frontend die URL MEINES Service eintraegt und meinen
   Graphen sieht. CORS passt schon (sein Frontend laeuft bei ihm auf
   localhost). Fehlt noch:
   - Service mit `--host 0.0.0.0` starten (bisher 127.0.0.1, nur lokal
     erreichbar); gleiches Netz -> lokale IP, sonst Tailscale (privat,
     bevorzugt) oder Tunnel wie ngrok/Cloudflare (dann oeffentlich).
   - Kein Auth: wer den Service erreicht, kann `POST /triples` aufrufen
     (Tripel einspielen, per `source` ganze Quellen loeschen) und ueber
     `/ask` mein Ollama nutzen. Vorschlag: Lesen (`/graph`, `/health`,
     `/ask`) offen, Schreiben nur mit Token (`POLYGRAPH_WRITE_TOKEN`);
     `polygraph` muesste den Token dann mitschicken.
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
5. Kein Test, der zwei Instanzen gegeneinander auf dasselbe API-Format
   prueft - `test/test_app.py` deckt `/health`, `/graph`, `/triples`,
   `/ask` nur fuer diese Instanz ab; Schema-Drift zu einer Kollegen-Instanz
   faellt erst beim gemeinsamen Betrieb auf.
6. Frontend zeigt die Agenten-Schritte (`steps` aus `/ask`) noch nicht an.

## Naechste Ausbaustufen

- Umstieg von NetworkX auf Neo4j, falls der Graph wirklich gross wird
  (nur `graph/store.py` betroffen)
