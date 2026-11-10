Du pruefst eine Antwort Satz fuer Satz: Ist jede Aussage durch die
nummerierten Tripel aus einem Wissensgraphen gedeckt?

Die Tripel sind englisch, die Saetze koennen in einer anderen Sprache sein
- vergleiche die Bedeutung, nicht den Wortlaut ("multiple sclerosis" =
"Multiple Sklerose").

Fuer jeden Satz:
- "belege": Nummern der Tripel, die die Aussage des Satzes stuetzen (nur
  Nummern aus der Liste unten, leer wenn keines passt). Die Nummern in
  eckigen Klammern im Satz sind nur die BEHAUPTETEN Belege - pruefe, ob sie
  wirklich passen.
- "begruendung": ein kurzer Satz auf {language} - was steht in den
  Tripeln, was im Satz, wo liegt ggf. der Unterschied?
- "urteil":
  - "gedeckt": jede inhaltliche Aussage des Satzes steht in den Tripeln.
  - "teilweise": der Kern ist belegt, aber ein Detail geht darueber hinaus.
  - "nicht_gedeckt": die Kernaussage steht nicht in den Tripeln oder
    widerspricht ihnen.
  - "vermutung": der Satz gehoert zum Abschnitt, der ausdruecklich als
    Vermutung gekennzeichnet ist ("Vermutung (nicht im Graphen belegt):"
    bzw. dasselbe in der Sprache der Antwort) - auch diese Ueberschrift
    selbst und alle Saetze danach.
  - "keine_aussage": der Satz behauptet nichts Inhaltliches (z.B. "Das
    steht nicht in den Tripeln, die mir vorliegen." oder eine reine Ueberleitung).

Achte besonders auf:
- Zahlen und Werte (stimmen sie mit value ueberein?)
- Richtung (erhoeht / senkt, verbessert / verschlechtert)
- Ursache statt Zusammenhang ("bewirkt" vs. "geht einher mit")
- Verallgemeinerung (nur an Maeusen / im Labor / in einem Land oder
  Zeitraum belegt, im Satz allgemein gueltig)
- "wird untersucht" / "koennte" im Tripel, im Satz als Tatsache
- Bedingungen (condition), die im Satz fehlen und die Aussage umkehren

KEIN Grund fuer "teilweise" oder "nicht_gedeckt":
- Umschreibungen in Alltagssprache, Uebersetzungen und Satzverbindungen
  ("dabei", "ausserdem")
- kurze Erklaerungen von Fachbegriffen in Klammern oder im Nebensatz
  (z.B. "OPCs (Vorlaeuferzellen der Myelin bildenden Zellen)") - das ist
  erlaubtes Allgemeinwissen
- kurze bildhafte Vergleiche, die nur einen Begriff veranschaulichen
  ("wie die Isolierung um ein Stromkabel")
- weggelassene Details (der Satz muss nicht alles aus dem Tripel nennen)
- einfache Rechnungen aus den Werten der Tripel (Differenz, Veraenderung in
  Prozent), wenn das Ergebnis stimmt - rechne nach; stimmt es nicht, ist der
  Satz "nicht_gedeckt"
- Vergleiche eines belegten Werts mit einer Zahl aus der FRAGE (z.B. "liegt
  ueber den gefragten 17 Prozent"), wenn der Vergleich stimmt - die Zahl aus
  der Frage muss in keinem Tripel stehen
- ein Satz, der nur sagt, was in den Tripeln fehlt ("Fuer 2024 liegt kein Wert
  vor") - das ist "keine_aussage"{domain_notes}

FRAGE (nur, damit du weisst, worauf die Antwort sich bezieht - sie ist kein Beleg):
{question}

TRIPEL:
{triples}

SAETZE:
{sentences}

Antworte als JSON-Liste mit genau einem Eintrag pro Satz, in derselben
Reihenfolge, "nr" wie oben.
