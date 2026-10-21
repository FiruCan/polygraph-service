Du bekommst eine Frage und die Liste aller Knoten eines Wissensgraphen.

AUFGABE:
Waehle die Knoten, die in der Frage GENANNT oder GEMEINT sind (Ausgangspunkte
der Suche). Beruecksichtige auch Synonyme, Abkuerzungen sowie Ober- und
Unterbegriffe (z.B. "Diabetes" -> "type 2 diabetes", "Muskeln" -> "muscles",
"skeletal muscle", "Zinsen" -> "interest rates", "key interest rate").
Die Knotennamen sind ENGLISCH, die Frage kann in jeder Sprache gestellt
sein (z.B. Deutsch oder Tuerkisch) - uebersetze die Begriffe der Frage
gedanklich ins Englische und waehle die passenden englischen Knoten.
Waehle NICHT die gesuchte Antwort: Die Antwort ergibt sich spaeter aus den
Kanten der gewaehlten Knoten.
Beispiel: Frage "Was senkt das Risiko fuer Krebs?" -> ["cancer"]

AUSGABEFORMAT:
Antworte AUSSCHLIESSLICH mit einem JSON-Array der exakten Knotennamen aus der
Liste, z.B. ["Knoten A", "Knoten B"]. Passt kein Knoten, gib [] zurueck. Keine
Erklaerungen, keine Markdown-Codeblock-Markierungen.

KNOTEN:
{nodes}

FRAGE:
{question}
