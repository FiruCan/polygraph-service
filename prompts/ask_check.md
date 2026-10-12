Du pruefst eine Antwort Satz fuer Satz: Ist jede Aussage durch die
nummerierten Tripel aus einem Wissensgraphen gedeckt?

Fuer jeden Satz:
- "belege": Nummern der Tripel, die die Aussage des Satzes stuetzen (nur
  Nummern aus der Liste unten, leer wenn keines passt). Die Nummern in
  eckigen Klammern im Satz sind nur die BEHAUPTETEN Belege - pruefe, ob sie
  wirklich passen.
- "begruendung": ein kurzer Satz - was steht in den Tripeln, was im Satz,
  wo liegt ggf. der Unterschied?
- "urteil":
  - "gedeckt": jede inhaltliche Aussage des Satzes steht in den Tripeln.
  - "teilweise": der Kern ist belegt, aber ein Detail geht darueber hinaus.
  - "nicht_gedeckt": die Kernaussage steht nicht in den Tripeln oder
    widerspricht ihnen.

Achte besonders auf:
- Zahlen und Werte (stimmen sie mit value ueberein?)
- Richtung (erhoeht / senkt, verbessert / verschlechtert)
- Ursache statt Zusammenhang ("bewirkt" vs. "geht einher mit")
- Verallgemeinerung (nur an Maeusen / im Labor belegt, im Satz fuer Menschen)
- "wird untersucht" / "koennte" im Tripel, im Satz als Tatsache
- Bedingungen (condition), die im Satz fehlen und die Aussage umkehren

KEIN Grund fuer "teilweise" oder "nicht_gedeckt":
- Umschreibungen in Alltagssprache und Satzverbindungen ("dabei", "ausserdem")
- kurze Erklaerungen von Fachbegriffen in Klammern oder im Nebensatz
  (z.B. "OPCs (Vorlaeuferzellen der Myelin bildenden Zellen)") - das ist
  erlaubtes Allgemeinwissen
- weggelassene Details (der Satz muss nicht alles aus dem Tripel nennen)

TRIPEL:
{triples}

SAETZE:
{sentences}

Antworte als JSON-Liste mit genau einem Eintrag pro Satz, in derselben
Reihenfolge, "nr" wie oben.
