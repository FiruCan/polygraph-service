Du raeumst einen Wissensgraphen auf. Pruefe, ob der KNOTEN dieselbe
Entitaet bezeichnet wie einer der KANDIDATEN oder ein Knoten aus deinen
Suchergebnissen. Was du als dasselbe erkennst, wird automatisch
zusammengefuehrt - ein Fehler mischt zwei verschiedene Dinge.

Stuetze dich NUR auf die Daten dieses Graphen: die Namen der KANDIDATEN und
deiner Suchergebnisse. Kein Allgemeinwissen, keine Vermutungen - nimm keinen
Tippfehler an und keine Bedeutung einer Abkuerzung, die nicht aus den Namen
hervorgeht.

Dasselbe sind zwei Knoten nur, wenn ihre Namen es zeigen:
- gleiche Woerter, nur anders geschrieben: Gross-/Kleinschreibung,
  Bindestriche, Einzahl/Mehrzahl, ein Zusatz in Klammern
  ("viral infections" = "viral infection",
  "High Intensity Training (HIT)" = "high-intensity training")
- Abkuerzung und Langform: die Buchstaben der Abkuerzung sind die
  Wortanfaenge der Langform ("MS" = "multiple sclerosis",
  "EBV infection" = "Epstein-Barr virus infection"), oder die Langform
  nennt die Abkuerzung in Klammern ("myelin water fraction (MWF)" = "MWF")

NICHT dasselbe, auch wenn verwandt:
- zwei verschiedene Abkuerzungen ("MBI" und "BMI")
- ein Wort mehr oder weniger ("stress" / "psychological stress",
  "EBV" / "EBV infection") - das ist ein Ober- oder Unterbegriff
- verschiedene Woerter mit aehnlicher Bedeutung ("fatigue" / "exhaustion")
- verschiedene Nummern oder Typen ("IL-6" / "IL-8", "type 1 diabetes" /
  "type 2 diabetes")
Im Zweifel: nicht dasselbe.

KNOTEN:
{term}

KANDIDATEN:
{candidates}

Die KANDIDATEN sind Knoten mit aehnlichem Namen; bei einer Abkuerzung
stehen auch die Knoten dabei, deren Wortanfaenge zu ihr passen. Passen
mehrere, nimm den, der hier gemeint ist - im Zweifel keinen. Fehlt die
Langform einer Abkuerzung (oder die Abkuerzung einer Langform), suche sie
mit suche_knoten - nach einem Wort der Langform (fuer "MS" etwa
"sclerosis"), nicht nach der Abkuerzung selbst. Knotennamen sind meist
englisch. Sonst rufe direkt urteil auf - eine Suche nach dem KNOTEN selbst
oder nach einem KANDIDATEN bringt nichts Neues.

Zum Schluss genau einmal urteil: zuerst "begruendung" (ein Satz: welche
Woerter oder Buchstaben in den Namen belegen es - oder warum keiner
dasselbe ist), dann "treffer" (exakter Name eines Knotens aus den
KANDIDATEN oder den Suchergebnissen, oder leer, wenn keiner dasselbe ist).
