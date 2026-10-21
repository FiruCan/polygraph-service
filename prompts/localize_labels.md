Du uebersetzt die Beschriftungen eines Wissensgraphen fuer die Anzeige in
die Sprache {language}. Es sind kurze Texte: Knotennamen (Begriffe), Typen
und Beziehungen (englisch mit Unterstrichen, z.B. "signaling_molecule",
"increases_risk_of") sowie Angaben an den Kanten (Werte, Bedingungen,
Belegarten).

FACHGEBIET: Der Graph ist aus den Artikeln entstanden, die bisher
importiert wurden. Seine haeufigsten Knotentypen zeigen, worum es geht:
{topics}

REGELN:
- Uebersetze jeden Text in den ueblichen Fachbegriff auf {language}, wie er
  in Fachartikeln oder allgemein verstaendlichen Texten zu diesem
  FACHGEBIET in dieser Sprache steht. Bei mehrdeutigen Woertern den Sinn
  nehmen, der zum FACHGEBIET passt.
- Texte mit Unterstrichen (Typen, Beziehungen) als normale Woerter
  uebersetzen, ohne Unterstriche ("increases_risk_of" -> auf Deutsch
  "erhöht Risiko für", "signaling_molecule" -> "Signalmolekül").
- Bedeutung genau erhalten: nichts verallgemeinern, nichts weglassen,
  nichts hinzufuegen. Einzahl/Mehrzahl beibehalten.
- Unveraendert lassen: Abkuerzungen und Codes (IL-6, BDNF, EDSS, DAX),
  Fachnamen wie Gene, Wirkstoffe oder Produkte, sofern sie in {language} gleich
  geschrieben werden, Eigennamen von Personen, Organisationen, Studien und
  Orten, Formeln, Einheiten und statistische Kennwerte.
- Zahlen bleiben dieselben, nur in der Schreibweise von {language}
  (Dezimalkomma oder Dezimalpunkt).
- Die Texte sind meist englisch, einzelne auch deutsch oder in einer
  anderen Sprache - auch diese uebersetzt du nach {language}.
- Ist ein Text schon auf {language}, bleibt er EXAKT so.

Gib fuer JEDEN Text der Liste genau einen Eintrag zurueck: "original" exakt
wie in der Liste, "uebersetzung" der Text auf {language}.

TEXTE:
{names}
