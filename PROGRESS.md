# Progress

## Stand

**Typ-Hierarchie (Speicher fertig, noch leer)**
- Grund: die Typen sind eine flache Liste, die aus den Artikeln waechst
  (506 Typen); eine Ontologie, die mitwaechst statt vorab eine Domain
  festzulegen: oben polygraphs domaenenneutrales Startvokabular als
  Wurzeln, darunter pro Typ ein Obertyp ("disease" -> "condition").
- Vorarbeit (2026-10-21): doppelte Typen zusammengefuehrt, ueber
  `POST /vocabulary/rename` nach Freigabe - 22 Umbenennungen an 135
  Knoten (Schreibvarianten wie "inflammatory lesions" ->
  "inflammatory_lesions", snake_case fuer haeufige Typen, "cell_type" ->
  "cell", "immunocytes" -> "immune_cell"); 521 -> 506 Typen. Backup
  `data/graph.backup-2026-10-21-203121.gml`. Probelauf (gemma4:26b ordnet
  die 52 Typen mit >= 3 Knoten je einer Wurzel zu): mit den 12 Wurzeln
  passten 28 % der Knoten nirgends hin; polygraph hat deshalb
  `condition`, `structure`, `activity` dazubekommen -> 5 %. Offen:
  `cell`, `gene`, `pathogen`. Die Zuordnung schwankt zwischen Laeufen -
  Hierarchie daher nur nach Freigabe.
- `data/graph.hierarchy.json` neben dem Graphen (`store.hierarchy_path`,
  Backups bekommen ihr Gegenstueck), nicht als Knoten im Graphen.
  `GraphStore.type_parents`, gespeichert/geladen mit `save()`/`load()`,
  atomar; ohne Hierarchie entsteht keine Datei. Nicht in git (wie
  `data/*.gml`).
- `GraphStore.set_type_parents()` / `POST /vocabulary/parents`: setzen und
  entfernen, alles oder nichts, Kreise -> 400. `GET /vocabulary` liefert
  `type_parents`.
- `rename_type_in_hierarchy()`: `POST /vocabulary/rename` (Typ) zieht die
  Hierarchie mit, auch ohne Knoten; ein schon vorhandener Zieltyp behaelt
  seinen Obertyp; keine Kreise, wenn ein Typ auf seinen Ober- oder
  Untertyp umbenannt wird.
- `POST /graph/backup` und `translate_graph.py apply` kopieren die
  Hierarchie mit.
- Tests: `test_store.py` (setzen, Kreise, Speichern/Laden, Umbenennen),
  `test_app.py` (Endpoint, Umbenennen ohne Knoten, Backup).
- Naechste Schritte: Steward in polygraph schlaegt Obertypen vor
  ("unterordnen"), dann nutzen - zuerst Duplikat-Pruefung (verschiedene
  Wurzeln -> nie zusammenfuehren), dann Extraktions-Prompt, dann Fragen.
- Hinweis: der laufende Service (seit 2026-10-19 15:32, ohne `--reload`)
  kennt `GET /vocabulary` noch nicht (404) - Neustart noetig, sonst
  scheitern polygraph-Importe, die vorher das Vokabular holen.

**Keine Domain mehr - das Fachgebiet kommt aus dem Graphen (fertig)**
- Grund: die Prompts waren auf Medizin angelegt ("biomedizinischer
  Wissensgraph", "im Gesundheitskontext", "Patienteninformationen"),
  spaeter sollen andere Themen dazu - pro Thema ein Graph, eine Instanz.
- `GET /vocabulary`: Typen und Relationen mit Haeufigkeit
  (`GraphStore.vocabulary()`); polygraph nimmt die haeufigen als bekanntes
  Vokabular der Extraktion statt einer Domain-Config.
- `GraphStore.topics()`: die 15 haeufigsten Knotentypen (beim Import plus
  die Typen der neuen Tripel - ein junger Graph hat kaum eigene) gehen als
  FACHGEBIET in die Prompts fuer Namen, Kanten-Angaben, Typen
  (`translate_*.md`) und Beschriftungen (`localize_labels.md`); daran
  entscheidet das Modell mehrdeutige Woerter. Live: "Bewegung" ->
  physical activity / motion / movement, "Spannung" -> tension / voltage
  je nach Fachgebiet (Gesundheit / Physik / Finanzen).
- Uebrige Prompts allgemein formuliert, Beispiele aus mehreren Gebieten
  (`ask_answer.md`: Methodendetails statt Labordetails, Belegstaerke auch
  "Schaetzung von Analysten"; `ask_check.md`, `ask_glossary.md`,
  `ask_select.md`, `ask_explain.md`, `suggest_questions.md`,
  `translate_texts.md`). `normalize_judge.md` und `dedupe_judge.md`
  unveraendert (Namensmuster, schon gemischt bzw. live abgestimmt).
- Tests: `test_store.py` (vocabulary, topics), `test_app.py` (Endpoint,
  Fachgebiet beim Import), `test_translate.py`, `test_localize.py`.

**Duplikat-Agent vollautomatisch (fertig, voller Lauf 2026-10-21)**
- Grund: Wunsch nach Zusammenfuehren ohne menschliche Freigabe, gestuetzt
  nur auf die Daten des Graphen - kein Allgemeinwissen, keine Vermutungen
  ("MBI ist ein Tippfehler fuer BMI" darf nie zu einem Merge fuehren).
- Freigabe = Agent UND Namen: `graph/dedupe.py::evidence()` prueft rein
  aus den Namen - gleiche Woerter anders geschrieben ("schreibweise"), oder
  jeder Buchstabe der Abkuerzung ist ein Wortanfang der Langform
  ("abkuerzung"; Kleinbuchstaben aus demselben Wort: IgE = ImmunoGlobulin E;
  Fuellwoerter tragen nichts bei; eine Abkuerzung in der Langform zaehlt nur
  ganz; eine Klammer am Ende darf einen Buchstaben aus dem Wortinneren
  nehmen: DHA = docosahexaenoic acid (DHA)). Passt eine Abkuerzung auf
  mehrere Langformen, muss die gewaehlte mehr gemeinsame Nachbarn haben als
  jede andere (`_rivals`; MS: multiple sclerosis 7, myelin status / muscle
  strength / ... 0), sonst `freigegeben: false` mit `mehrdeutig`.
- Kandidaten zusaetzlich aus den Namen (`name_partners`, ~3 s fuer 3.000
  Knoten): der Agent hatte "multiple sclerosis" zwar gesucht und gefunden,
  aber verworfen, weil es "keiner der Kandidaten" war. Prompt
  `prompts/dedupe_judge.md` geerdet (nur Namen, kein Allgemeinwissen,
  Ober-/Unterbegriffe und Synonyme mit anderen Woertern sind nicht dasselbe),
  Suchtreffer heissen "Weitere KANDIDATEN aus der Suche".
- Verworfen: lockere Regel mit einem Buchstaben aus dem Wortinneren -
  liess "MS" = Masitinib, "CNS" = chronic stress, "MBI" = MS brain zu.
- `POST /graph/backup` (Kopie von `data/graph.gml` mit Zeitstempel);
  polygraph `dedupe.py --auto`: suchen, Backup, freigegebene zusammenfuehren.
- Live (103 Testgruppen, 2026-10-19): 18 Paare freigegeben, alle richtig
  (MS -> multiple sclerosis, EBV -> Epstein-Barr virus, CNS, BDNF, SLE,
  SDMT, MTR -> magnetization transfer ratio, MBI -> Mindfulness-based
  interventions (MBIs), viral infections -> viral infection, ...), keine
  falsche Zusammenfuehrung; der Code stoppte "EBV infection" -> "EBV" und
  "relapsing MS" -> "MS relapses". 2.9 s pro Gruppe (alter Richter 1.9 s).
- Grenzen: bewusst nicht automatisch - Synonyme mit anderen Woertern
  ("fatigue" / "exhaustion"), Buchstaben aus dem Wortinneren ("CVD" =
  cardiovascular disease, "AMPK", "IL-6" = interleukin-6), Abkuerzungen,
  die die Nachbarn nicht entscheiden (BBB, DHA).
- Behalten: bei Abkuerzung und Langform immer die Langform ("Epstein-Barr
  virus" statt "EBV") - Antworten sind fuer Laien; sonst wie bisher der
  Name mit mehr Kanten.
- Probelauf (`dedupe.py --auto --limit 50`, 183 s, 70 LLM-Aufrufe): 10
  zusammengefuehrt, alle richtig (u.a. CNS, EBV, VEP, BDNF, NLR, MWF);
  3.014 -> 3.004 Knoten. Damals galt noch "mehr Kanten bleibt" - BDNF, MWF,
  NLR, EBV infection danach per `/nodes/rename` auf die Langform umbenannt.
  Backups: `data/graph.backup-2026-10-19-151533.gml` (vor dem Probelauf),
  `-153159.gml` (vor dem Umbenennen).
- Voller Lauf (`dedupe.py --auto`, 1.343 Richter-Laeufe, 1.680
  LLM-Aufrufe): 39 Vorschlaege, 32 freigegeben und zusammengefuehrt,
  3.004 -> 2.972 Knoten, 4.479 -> 4.473 Kanten; Backup
  `data/graph.backup-2026-10-21-194011.gml`. U.a. MS -> multiple sclerosis
  (28 Kanten), MS patients, MS relapses, PPMS/SPMS -> primary/secondary
  progressive MS, OPCs (39 Kanten), OLCs, CRS, MTR, SDMT, DHA ->
  docosahexaenoic acid (DHA) (Nachbarn gegen "digital health
  applications"), Mehrzahl-Varianten (relapse rates, psychiatric
  disorders, ...). Fraglich: "walking" -> "walking (T25FW)" - die Klammer
  ist hier keine Abkuerzung der Woerter davor, sondern ein Test. Gestoppt
  (kein Beleg): walking capabilities / walking ability, OL identity / OLC
  identity, disorders of bladder function control / bladder function
  disorders; verpasst wegen Mehrdeutigkeit: BBB, NO; ohne Beleg: AMPK.
  Dauer 187.672 s (52 Std.), weil der Mac zwischendurch schlief - reine
  Rechenzeit laut Stichprobe gut 1 Std. Behalten bei Schreibvarianten: der
  Name mit mehr Kanten, daher teils Mehrzahl ("inflammations", "infections").
- Tests: `test/test_dedupe.py` (34 Namensfaelle aus den Live-Tests,
  Mehrdeutigkeit, Kandidaten aus Namen, Langform bleibt), `test/test_app.py`
  (Backup); polygraph `test/test_dedupe.py` (`--auto`).

**Duplikat-Richter als Agent (fertig, noch nicht ueber den ganzen Graphen gelaufen)**
- Grund: der Richter (ein Aufruf, `normalize.judge_verdict`) durfte nur
  unter den Embedding-Kandidaten waehlen - bei Abkuerzungen fehlt dort oft
  die Langform: "MS" bekommt 20 Kandidaten von "MS diagnosis" bis
  "relapsing MS", "multiple sclerosis" ist nicht dabei.
- `graph/dedupe.py::judge()` + `prompts/dedupe_judge.md`: Agent mit Ollama
  Tool Calling wie der Frage-Agent, ohne Framework (LangGraph, smolagents,
  Langflow erwogen: fuer eine Schleife mit zwei Werkzeugen zu schwer, und
  deren aktuelle Versionen brauchen Python >= 3.10, hier laeuft 3.9).
  Werkzeuge `suche_knoten` (Teilstring; Gross-/Kleinschreibung und
  Bindestriche egal, kuerzeste Namen zuerst) und `urteil`; max. 3 Runden,
  sonst erzwungenes JSON-Urteil (enum auf gesehene Knoten). Treffer nur aus
  gesehenen Knoten. Die Schleife ueber alle Knoten bleibt im Code.
- API additiv: `llm_aufrufe` im Ergebnis, `schritte` pro Vorschlag;
  polygraph `dedupe.py` zeigt beides.
- Verworfen: erste Fassung mit Werkzeug `kanten_von` (Tripel eines
  Knotens) und Typen im Prompt - schaute fast immer nach (3.8 s statt 1.9 s
  pro Gruppe) und erklaerte danach Verwandtes fuer "im Kontext synonym"
  (Stress -> psychological stress, Helicobacter pylori -> ... infection,
  blood concentration -> blood values); ein falscher Typ machte HLA-A*02 zu
  H2-aa. Ebenso verworfen: Prompt-Regel "Abkuerzung = Wortanfaenge der
  Langform" - verhinderte MBI -> BMI, liess den Agenten aber gefundene
  Langformen uebergehen (CVD, EBV, OLCs).
- Live (Graph mit 3.014 Knoten, 1.341 Gruppen, 164 davon mit Abkuerzung),
  Agent gegen alten Richter auf denselben Gruppen:
  - 43 Gruppen in Graph-Reihenfolge: 11 statt 8 Vorschlaege. Neu und richtig:
    MS -> multiple sclerosis, "High Intensity Training (HIT)" ->
    high-intensity training, EBV infection -> Epstein-Barr virus infections
    (alt: -> EBV). Neu und fraglich: genetic factors -> genetics,
    environmental factors -> external influences. 2.5 s statt 1.9 s pro Gruppe.
  - 60 Abkuerzungs-Gruppen (30 erst zur Kontrolle gezogen): 5 richtige
    Treffer (BDNF, CVD, EBV, SLE, NLR) statt 1 (NLR); falsch MBI -> BMI
    ("Tippfehler") und MTR -> methotrexate (im Graphen: magnetization
    transfer ratio), beim alten A2B5 -> A2B5+ OPCs und FF-VEP -> multifocal
    VEP. 3.6 s statt 2.2 s pro Gruppe.
  - Hochgerechnet ~1 Std. fuer den ganzen Graphen (alter Richter ~45 Min.).
- Grenzen: Grenzfaelle kippen zwischen Laeufen trotz temperature 0 (OLCs,
  genetic factors je einmal ja, einmal nein); verpasst u.a. VEP -> visual
  evoked potentials (gefunden, aber verworfen) und SDMT (falsche Langform
  geraten) - Freigabe deshalb inzwischen an Belege aus den Namen
  gebunden (siehe "Duplikat-Agent vollautomatisch").
- Tests: `test/test_dedupe.py` (Ollama gemockt).

**Antwort-Pruefer (fertig)**
- Grund: Antworten gehen als PDF weiter - eine falsch belegte Aussage ist
  dort teurer als im Graphen. Gleiches Prinzip wie der Pruef-Agent bei der
  Extraktion (polygraph `verify_triples`).
- `graph/ask.py::check_answer()`, `prompts/ask_check.md`: ein LLM-Aufruf
  fuer alle Saetze, pro Satz erst Belege + Begruendung, dann Urteil
  (gedeckt / teilweise / nicht_gedeckt / vermutung / keine_aussage).
  Geprueft wird gegen die zitierten Tripel, auch Saetze ohne eigenes [n].
  Vermutungs-Abschnitt: auf Deutsch am Text erkannt, in anderen Sprachen
  ordnet ihn das LLM zu. Scheitert die Pruefung: `status: "ungeprueft"`,
  Antwort unveraendert.
- `/ask` liefert `pruefung`; polygraph markiert nicht gedeckte Saetze im
  Frontend (Begruendung als Tooltip) und im PDF (Abschnitt "Belegpruefung").
- Live (echter Graph, eine Frage zu Krafttraining/Herz/Diabetes): Original
  4/4 Saetze gedeckt; 5 eingebaute Fehler (Zahl, Richtung, Bedingung,
  erfundene Aussage mit Beleg, "klinische Studien beweisen" statt
  Bevoelkerungsstudien) alle gefunden, jeweils nur der falsche Satz
  markiert. Rechenzeit ~9 s (1.4 s Prompt, 7 s Ausgabe); gemessen 42-68 s,
  weil Ollama gleichzeitig andere Anfragen bearbeitete.
- Grenzen: nur an einer Frage live geprueft; Antwortzeit pro Frage +~10 s.

**Duplikat-Aufraeumer (fertig, noch nicht ueber den ganzen Graphen gelaufen)**
- `graph/dedupe.py`, `POST /duplicates/find`, `POST /nodes/merge`
  (`store.merge_nodes`: Kanten umhaengen, Schleifen zwischen den beiden
  verwerfen, gleiche Relation + Quelle zusammenlegen); Freigabe-Ablauf in
  polygraph `dedupe.py` (wie der Vokabular-Steward).
- Kandidaten: 0.75 und max. 5 pro Knoten; Abkuerzungen 0.55 und max. 20
  ("MS" ~ "multiple Sklerose" nur 0.66). Gemessen am Graphen (2.762
  Knoten): ~980 Richter-Aufrufe a ~4.7 s -> ~75 Min.
- Probelauf (30 Aufrufe): 3 Vorschlaege, 2 richtig, 1 falsch ("Konzentration
  im Blut" -> "concentration") - deshalb nur mit Freigabe.
- Voller Lauf erledigt (siehe "Duplikat-Agent vollautomatisch").

**Graph komplett Englisch, Fragen/Antworten in waehlbarer Sprache (fertig, Bestand umgestellt)**
- Grund: Knotennamen standen in der Sprache des Quelltextes - "Multiple
  Sklerose" neben "multiple sclerosis", "ZNS" neben "CNS". Die
  Synonym-Erkennung findet solche Paare ueber Sprachgrenzen schlecht.
- `graph/translate.py` + `prompts/translate_names.md`: uebersetzt Namen
  paketweise (40 pro LLM-Aufruf, ~30 s), schon englische Namen,
  Abkuerzungen, Gen-/Medikamentnamen und Eigennamen bleiben. Kaputte oder
  fehlende Antwort -> Name bleibt unveraendert.
- Import: `normalize_triple` uebersetzt Subjekt/Objekt vor dem
  Synonym-Abgleich (exakt bekannte Namen ohne LLM-Aufruf).
- Bestand: `translate_graph.py plan|apply` ueber `POST /nodes/rename`
  (`store.rename_node`, faellt auf `merge_nodes` zurueck, wenn der
  englische Name schon existiert). Reine Gross-/Kleinschreibungs-
  Aenderungen werden ausgelassen.
- Sprache: `language` an `/ask`, `/questions/suggest`, `/explain`
  (Standard "Deutsch"), Platzhalter `{language}` in den Prompts.
  `ask_select.md` und das Werkzeug `suche_knoten` wissen, dass die Knoten
  englisch heissen - Frage darf in jeder Sprache kommen.
- Live geprueft: Stichprobe von 48 echten Knoten sinnvoll uebersetzt;
  Fragevorschlaege auf Tuerkisch.
- Kanten-Angaben (value, condition, evidence_level) ebenfalls englisch:
  eigener Prompt `prompts/translate_details.md` (Dezimalpunkt, englische
  Studientypen, Kennwerte/Quellenangaben unveraendert), beim Import und
  per `POST /edges/rewrite` im Bestand. `/triples` uebersetzt alle neuen
  Namen und Angaben vorab in wenigen Paketen.
- Ersatzfragen (`suggest.py::fallback_question`) englisch wie der Graph.
- Frontend (polygraph `kg/`): Sprach-Dropdown mit Flaggen (Deutsch,
  English, Tuerkce) neben dem Fragefeld, im Browser gemerkt; geht an
  `/ask`, `/questions/suggest`, `/explain`. Im Browser geprueft:
  Vorschlaege und Antwort auf Tuerkisch.
- Bestand umgestellt (2026-10-17): 749 Knoten umbenannt, 14
  zusammengefuehrt, 606 Kanten-Angaben; Backup
  `data/graph.backup-2026-10-17-192413.gml`. Danach geprueft: Namen,
  Angaben und alle 282 Relationen englisch - aber rund 80 der 540 Typen
  noch deutsch ("Krankheiten", "Gehirn", ...), die waren nicht dabei.
- Typen deshalb ebenfalls (2026-10-19): eigener Prompt
  `prompts/translate_types.md` (snake_case bleibt snake_case:
  "infektionskrankheit" -> "infectious_disease"); beim Import uebersetzt
  `/triples` nur noch unbekannte Typen (`store.known_types`); Bestand per
  `translate_graph.py plan --nur typen` + `apply` ueber
  `POST /vocabulary/rename`. Live: Stichprobe von 18 echten Typen sinnvoll.
- Typen im Bestand umgestellt (2026-10-19): 87 Typen an 95 Knoten, davon
  3 von Hand korrigiert/ergaenzt ("CD4+ T cells", "Fampridin" fehlte im
  Lauf, ein in den Typ gerutschter Linking-Hinweis "EDSS (im Graphen
  bereits als: EDSS 4)" -> "EDSS"); Backup
  `data/graph.backup-2026-10-19-141455.gml`. Danach 532 Typen, keiner
  mehr deutsch.
- Offen: Service muss fuer die Typ-Uebersetzung beim Import neu
  gestartet werden. `/passages` in
  polygraph sucht den (jetzt englischen) Begriff im Quelltext - in
  deutschen Artikeln findet er dann nichts. Typen allgemein unordentlich:
  419 der 540 Werte sind kein Vokabular, sondern Begriffe ("small
  molecules"), 443 kommen nur einmal vor - vermutlich aus der Extraktion.

**PDF-Export nach polygraph umgezogen (fertig)**
- `POST /export/pdf`, `GET /output/...` und `graph/export.py` sind weg; den
  Export macht jetzt polygraph selbst (`ingest_app.py`, PDFs in
  `polygraph/output/`). reportlab ist keine Abhaengigkeit mehr.

**Fragenvorschlaege: keine Wiederholungen, detailreicher (fertig)**
- Grund: dieselben Fragen kamen immer wieder (Knoten nur aus den Top 10,
  kein Gedaechtnis) und waren kurz und allgemein (max. 12 Woerter, Details
  der Kanten nicht im Prompt).
- `graph/suggest.py`: Knoten aus allen mit Grad >= 2, gewichtet nach
  Wurzel des Grads; `SuggestionHistory` merkt sich die letzten 300
  Ausgangspunkte und laesst sie aus (alles verbraucht -> von vorn). Neue
  Arten "detail" (Kante mit Bedingung/Wert/Evidenz) und "vergleich" (zwei
  Knoten, gleiches Ziel), reihum mit "knoten" und "pfad". Fakten im Prompt
  mit [Wert; Bedingung; Evidenz], pro Knoten zufaellig, Details zuerst.
- Prompt: mindestens ein Detail aufgreifen, bis ca. 25 Woerter,
  verschiedene Frageanfaenge; temperature 0.9.
- Gemessen am echten Graphen (904 Knoten): 10 Klicks x 5 -> 50
  Ausgangspunkte, 0 doppelt. Live: Fragen nennen Bedingungen, Gruppen,
  Studienart.

**Keine eigene Oberflaeche mehr (fertig)**
- Grund: der Service soll nur API sein. `static/` entfernt, kein
  StaticFiles-Mount mehr in `app.py` (`/` -> 404). Die Seite lebt jetzt in
  polygraph (`kg/`, Port 8001) und ruft die API per CORS auf.
- Tests: 95 bestanden.

**Frontend: deutliches Feedback + PDF-Export (fertig)**
- Grund: nach Klick auf "Fragen vorschlagen" bzw. einen Vorschlag war nicht
  zu sehen, ob etwas passiert (Antwort dauert 1-2 Minuten, nur eine kleine
  graue Statuszeile); ausserdem soll man Frage + Antwort weitergeben koennen.
- Ursachen: (1) laufender Service war noch der alte Prozess (404 auf
  /questions/suggest), (2) Browser nutzte die gecachte alte app.js -> jetzt
  `app.js?v=N`, (3) im Dark Mode zeichnete der Browser den Hintergrund
  dunkel, die Schrift blieb schwarz -> feste helle Farben (`color-scheme:
  light`).
- Feedback: Buttons zeigen "Vorschlaege werden erzeugt..." bzw. "Laeuft...",
  blauer Kasten "Frage wird beantwortet ... N s" mit Sekundenzaehler,
  angeklickter Vorschlag markiert, Seite scrollt zur fertigen Antwort.
- PDF-Export: Button "Als PDF speichern" (aktiv, sobald eine Antwort da
  ist) schickt die angezeigte Antwort an `POST /export/pdf`; der Service
  schreibt `output/<Frage>.pdf` (Dateiname = Frage ohne "?" und ohne
  verbotene Zeichen, nie ueberschreiben: " (2)" usw.), Inhalt wie die linke
  Seite im Frontend: Frage, Datum + Service, relevante Knoten, Antwort,
  Belege mit Quellen (sichere fett, unsichere blass). `graph/export.py`,
  reportlab mit Arial fuer Umlaute/Sonderzeichen. Zuerst als Browser-
  Druckdialog gebaut - verworfen: Browser darf nicht in einen festen Ordner
  schreiben, und in Safari ohne Drucker ist "Drucken" ausgegraut.
- Gespeichert wird immer auf dem Server, der die Seite ausliefert - auch
  wenn das Frontend gerade die Kollegen-Instanz abfragt.
- Tests: `test/test_export.py`, `test_app.py`. Live geprueft: "Was bewirkt
  Clemastin?" -> `output/Was bewirkt Clemastin.pdf`.

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
