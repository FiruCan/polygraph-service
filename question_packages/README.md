# Fragenlisten

Eine Fragenliste (Paket) arbeitet Argos Frage für Frage ab. Gestartet wird sie
in Metis unter „Fragenlisten“. Die Antworten zeigt Metis dort unter „Antworten“.

- **Vorgegeben:** `question_packages/<fachgebiet>/<name>.json` hier im Repo, z. B. die
  Buffett-Fragen zu Coca-Cola.
- **Eigene:** in Metis mit „Datei hochladen …“. Sie landen in
  `data/<fachgebiet>/question_packages/` und gehören nicht ins Repo. Der Dateiname wird
  zum Namen der Liste. Eine gleichnamige eigene Liste wird ersetzt, eine
  vorgegebene nicht.

## Formate

Textdatei (`.txt`), eine Frage pro Zeile; `#` setzt die Stufe der folgenden
Fragen, Aufzählungszeichen am Zeilenanfang fallen weg:

```
# 1 Geschäft verstehen
1. Was stellt Apple her?
2. Wer sind die Kunden von Apple?

# 2 Burggraben
- Mit wem konkurriert Apple?
```

JSON (`.json`), wie `finance/warrenbuffett_cocacola_questions.json`. Nötig ist
nur `fragen`. Eine Frage darf ein bloßer Text sein. Fehlt die `id`, wird sie
durchgezählt (`frage_1`, …):

```json
{
  "titel": "Apple",
  "firma": "Apple",
  "ticker": "AAPL",
  "fragen": [
    {"id": "produkte", "stufe": "1 Geschäft verstehen", "frage": "Was stellt Apple her?"},
    "Mit wem konkurriert Apple?"
  ]
}
```
