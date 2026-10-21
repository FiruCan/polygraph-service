Du schlaegst Beispielfragen an einen Wissensgraphen vor. Zu jedem
Ausgangspunkt unten siehst du die Fakten, die der Graph dazu enthaelt. In
eckigen Klammern stehen Details zu einem Fakt: Wert, Bedingung, Evidenz.
Formuliere pro Ausgangspunkt GENAU EINE Frage auf {language}.

REGELN:
- Die Frage muss sich mit den angegebenen Fakten beantworten lassen - frage
  nichts, wozu keine Fakten da sind.
- Detailreich: Wenn ein Fakt Details hat, greife mindestens eines davon in
  der Frage auf (z.B. die Bedingung, die Gruppe, den Zeitraum, die
  Groessenordnung, die Art des Belegs) - aber verrate die Antwort nicht.
- Bei Art "detail": frage nach dem Wie/Wann/Wie stark/Wie gut belegt der
  Beziehung (z.B. "Unter welchen Umstaenden senkt gesunder Schlaf die
  Sterblichkeit, und welche Rolle spielt dabei die Ernaehrung?").
- Bei Art "knoten": eine offene, aber konkrete Frage zu diesem Begriff, die
  zwei oder mehr der Fakten verbindet.
- Bei Art "pfad": frage nach dem Zusammenhang zwischen Anfang und Ende, ohne
  die Zwischenschritte zu verraten (z.B. "Ueber welche Mechanismen koennten
  Myokine das Demenzrisiko beeinflussen?").
- Bei Art "vergleich": frage, wie sich die beiden ersten Begriffe in ihrer
  Wirkung auf das Ziel unterscheiden oder aehneln.
- Abwechslung: keine zwei Fragen duerfen mit denselben zwei Woertern
  beginnen; nutze verschiedene Frageformen (Wie, Unter welchen Bedingungen,
  Welche Rolle, Inwiefern, Was unterscheidet, Wie gut belegt ...).
- Natuerlich formuliert, wie eine neugierige Fachperson fragen wuerde;
  hoechstens ca. 25 Woerter; keine Relationsnamen wie "reduces_risk_of".
- Die Fakten sind englisch. Uebertrage Begriffe in die Fragesprache, wo es
  dort eine uebliche Bezeichnung gibt ("multiple sclerosis" -> auf Deutsch
  "Multiple Sklerose"); Fachnamen ohne solche Bezeichnung (Gene,
  Produkte, Codes) bleiben, wie sie sind. Die Frage selbst auf {language}.

AUSGANGSPUNKTE:
{seeds}

Antworte als JSON-Array mit genau einem Eintrag pro Ausgangspunkt, in
derselben Reihenfolge: {{"nr": <Nummer>, "frage": "..."}}
