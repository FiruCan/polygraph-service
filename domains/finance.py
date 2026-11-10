"""
finance.py
----------
Profil Finanzen/Boerse. Werte wie Kurse, Zinsen und Kennzahlen gelten nur
zu einem Zeitpunkt und in einer Waehrung - deshalb neben value, condition
und evidence_level (hier die Belegart: berichtet, Analystenschaetzung,
Prognose) die Angaben as_of (Stichtag) und currency. Die ersten drei heissen
wie in der Medizin, damit Oberflaechen sie ohne Anpassung zeigen.
Startvokabular aus polygraph (evals/configs/finance.json).
"""

from domains.base import DomainProfile, Qualifier, Variant

QUALIFIERS = (
    Qualifier("value", "value", "Wert", description=(
        "Zahlen, Betraege und Veraenderungen, die die Beziehung quantifizieren,\n"
        "  woertlich mit Einheit (z.B. \"4,25 Prozent\", \"minus 12 Prozent\", \"3,8 Milliarden\").\n"
        "  Steht nichts im Text: null.")),
    Qualifier("condition", "condition", "Bedingung", description=(
        "Markt, Region, Segment oder Szenario, unter denen die Aussage gilt\n"
        "  (z.B. \"Euroraum\", \"Segment Elektroautos\"). Zeitangaben gehoeren in \"as_of\".\n"
        "  Sonst: null.")),
    Qualifier("evidence_level", "evidence", "Belegart", description=(
        "Art des Belegs, nur falls im Text genannt (z.B. \"Geschaeftsbericht\",\n"
        "  \"Quartalsbericht\", \"Analystenschaetzung\", \"Prognose\", \"Ankuendigung\").\n"
        "  Sonst: null. Nicht raten.")),
    Qualifier("as_of", "as of", "Stichtag", description=(
        "Zeitpunkt oder Zeitraum, auf den sich die Aussage bezieht, aus dem Text\n"
        "  (z.B. \"Juli 2023\", \"zweites Quartal 2024\", \"2021\"). Ist die Angabe relativ (\"heute\",\n"
        "  \"gestern\", \"seit Jahresbeginn\", \"drittes Quartal\" ohne Jahr) und steht unten ein\n"
        "  Erscheinungsdatum, ergaenze damit Datum bzw. Jahr (bei Erscheinungsdatum 2025-03-14:\n"
        "  \"heute\" -> \"14.03.2025\", \"seit Jahresbeginn\" -> \"seit Jahresbeginn 2025\").\n"
        "  Ohne Erscheinungsdatum woertlich lassen. Nennt der Text keine Zeit: null - das\n"
        "  Erscheinungsdatum dann nicht einsetzen.")),
    Qualifier("currency", "currency", "Waehrung", translate=False, description=(
        "Waehrung eines Betrags in \"value\" als ISO-Code (z.B. \"EUR\" fuer Euro,\n"
        "  \"USD\" fuer US-Dollar), nur wenn der Text sie nennt. Sonst: null."),
              pattern="^[A-Z]{3}$"),
    # Ein Tripel kann nur etwas behaupten: "hob die Prognose nicht an" blieb sonst dem Zufall ueberlassen
    # (2026-11-09: 4 von 2320 Kanten mit Verneinung, und nur als Wort im value)
    Qualifier("negated", "negated", "verneint", translate=False, description=(
        "Nur \"ja\", wenn der Text die Aussage des Tripels verneint oder dementiert\n"
        "  (\"hob die Prognose nicht an\", \"dementierte die Uebernahme\"). Sonst: null."),
              pattern="^ja$"),
)

# technology und organization: im Graphen 122 Knoten "technology" (chip
# packaging, Hybrid Bonding) und 40 Universitaeten, Institute und Boersen
# ohne passenden Profil-Typ (2026-11-07). index: ohne ihn fehlte mit festen
# Typen der Dax-Schlusskurs (Eval holdout_marktbericht)
ENTITY_TYPES = (
    "company", "sector", "person", "financial_metric", "event", "regulation", "product",
    "central_bank", "rating_agency", "currency", "technology", "organization", "index",
)

# sells_stake_in: Verkaeufe fielen weg, weil keine Relation passte; eine alte Beteiligung
# blieb dann der letzte Stand (0 von 73 holds_stake_in-Kanten nannten einen Verkauf).
# produces und plans: im Finanz-Graphen 12- bzw. 16-mal ohne passende Profil-
# Relation (Hersteller -> Produkt, Ziele und Vorhaben eines Unternehmens)
RELATION_TYPES = (
    "influences", "competes_with", "reports", "acquires", "affects_metric", "employed_by",
    "increases_risk_of", "triggers_decline_of", "correlates_with", "belongs_to_class",
    "regulated_by", "increases", "decreases", "sets", "holds_stake_in", "sells_stake_in", "pays_dividend",
    "rates", "forecasts", "produces", "plans",
)

PROMPT_NOTES = {
    "answer": (
        "- Kurse, Zinsen und Kennzahlen gelten nur zu einem Zeitpunkt: nenne den Stichtag\n"
        "  (as of) und die Waehrung (currency), wenn das Tripel sie hat. Fehlt der Stichtag,\n"
        "  sag, dass offen ist, wann der Wert galt.\n"
        "- Gibt es fuer dieselbe Kennzahl mehrere Staende, nimm den neuesten und nenne sein\n"
        "  Datum; aeltere Werte nur als Vergleich. \"published\" ist das Erscheinungsdatum der\n"
        "  Quelle: Ein \"seit Jahresbeginn\" aus einem alten Artikel ist nicht der heutige Stand.\n"
        "- Trenne berichtete Zahlen von Prognosen und Analystenschaetzungen (evidence).\n"
        "- Keine Anlageempfehlung und keine Kursprognose ueber die Tripel hinaus - auch\n"
        "  nicht im Abschnitt mit der Vermutung.\n"
        "- Fragt jemand nach Gruenden fuer Kauf oder Verkauf: nenne beide Seiten, jede mit Namen\n"
        "  und Beleg, und lass die Entscheidung offen.\n"
        "- Ein Tripel mit \"negated: ja\" ist eine Verneinung: Gib es als Verneinung wieder.\n"
        "- Fehlt etwas in den Tripeln, schreib, dass dazu nichts vorliegt - nicht, dass es nicht so ist.\n"
        "- Ein Wert fuer ein Geschaeftsjahr gilt fuer das ganze Jahr (\"fiscal year\", \"twelve months\").\n"
        "  Quartale, sechs oder neun Monate sind keine Jahreswerte. Das Geschaeftsjahr einer Firma\n"
        "  endet oft nicht im Dezember.\n"
        "- Ob eine Firma die Erwartungen uebertroffen hat: vergleiche den berichteten Wert mit der\n"
        "  Schaetzung (consensus, estimate) fuer dasselbe Quartal und nenne die Differenz.\n"
        "  Eine Schaetzung steht oft unter dem Namen ihres Anbieters oder als \"Consensus Estimate\"\n"
        "  im Subjekt (\"... Consensus Estimate --forecasts--> earnings per share\"): Sie gilt fuer die\n"
        "  Firma, um die es in den Tripeln daneben geht. Fehlt sie nur fuer einige Quartale, vergleiche\n"
        "  die Quartale, fuer die es sie gibt.\n"
        "- \"earnings per share\" (nach GAAP) und \"adjusted earnings per share\" (bereinigt, non-GAAP)\n"
        "  sind zwei verschiedene Kennzahlen, kein Widerspruch zwischen Quellen: sag, welche du nennst,\n"
        "  und vergleiche eine Schaetzung mit dem bereinigten Wert, wenn sie bereinigt ist."
    ),
    # Ohne diese Hinweise kam zu "Gewinnerwartungen der Analysten" nur "analyst expectations" -
    # die Schaetzung stand als "Zacks Consensus Estimate" im Graphen und fehlte im Prompt
    "terms": (
        "- Erwartungen von Analysten: \"estimate\", \"consensus\", \"expectations\", \"surprise\",\n"
        "  \"beat\", \"miss\".\n"
        "- Geschaeftsjahre: \"fiscal year\", \"annual\", \"twelve months\"; Quartale: \"quarter\".\n"
        "- Kennzahlen mit ihrer Abkuerzung: \"earnings per share\" und \"EPS\"."
    ),
    "check": (
        "- Stichtag (as of) und Waehrung (currency): nennt ein Satz einen Wert mit einem\n"
        "  anderen Zeitpunkt oder einer anderen Waehrung als das Tripel, oder macht er einen\n"
        "  Wert ohne Stichtag zum heutigen Stand, ist er hoechstens \"teilweise\".\n"
        "- Eine Anlageempfehlung oder Kursprognose ist nie \"gedeckt\". Eine belegte Einschaetzung\n"
        "  mit Namen (\"Needham stuft auf Kaufen\") ist keine Anlageempfehlung.\n"
        "- Ein Tripel mit \"negated: ja\" ist eine Verneinung: Behauptet der Satz das Gegenteil,\n"
        "  ist er \"nicht_gedeckt\"."
    ),
    "suggest": (
        "- Hat ein Fakt einen Stichtag, greife ihn in der Frage auf (z.B. \"im Juli 2023\").\n"
        "- Keine Fragen nach Kaufempfehlungen oder kuenftigen Kursen."
    ),
    # Aus Testlaeufen mit Quartals-, Zins- und Beteiligungstexten: ohne diese
    # Regeln wurde die Kennzahl zum Subjekt (EBIT --reports--> EBIT, vom
    # Pruef-Agenten verworfen), der Vorjahreswert ging verloren, "sank" und
    # "herabgestuft" verschwanden in affects_metric und "je Aktie" im value.
    # Beispiele absichtlich nicht aus diesen Testtexten (wie EXAMPLE_TEXT)
    # Aktienkurs eigens genannt: "Die Aktie stieg" ergab trotz der Regel Aktie
    # --sets--> Kurs bzw. X --increases--> Aktie (Eval kurs_heute)
    "extract": (
        "- Subjekt einer Kennzahl (Umsatz, EBIT, Marge, Dividende, Kurs, Rendite) ist das\n"
        "  Unternehmen, der Markt oder das Wertpapier, dem sie gehoert - nie die Kennzahl selbst.\n"
        "  \"Der Umsatz sank um 8 Prozent\" in einem Text ueber Henkel ergibt Henkel --reports--> Umsatz.\n"
        "  Ebenso Aktienkurs und Boersenwert: \"Die Aktie von Henkel stieg um 2 Prozent auf 80 Euro\"\n"
        "  ergibt Henkel --reports--> Aktienkurs (value \"plus 2 Prozent auf 80 Euro\"), nicht\n"
        "  Aktie --> Kurs und nicht Henkel --increases--> Aktie.\n"
        "- Nennt der Text fuer dieselbe Kennzahl Werte zu mehreren Zeitpunkten (aktuell und\n"
        "  Vorjahr, alte und neue Prognose), erzeuge je Zeitpunkt ein eigenes Tripel mit eigenem\n"
        "  \"as_of\". Ein relativer Zeitpunkt (\"Vorjahresquartal\") wird ausgeschrieben, wenn der\n"
        "  Text ihn eindeutig macht (\"drittes Quartal 2023\" neben \"drittes Quartal 2024\").\n"
        "- Wirkt etwas auf eine andere Groesse (Zinsen auf Kurse, Nachfrage auf Gewinn), gehoert\n"
        "  die Richtung in die Relation: \"increases\" bzw. \"decreases\" statt \"affects_metric\"\n"
        "  oder \"influences\". Veraendert sich eine eigene Kennzahl des Subjekts (\"Henkel verlor\n"
        "  8 Prozent Umsatz\"), ist das \"reports\" mit der Richtung im \"value\" (\"minus 8 Prozent\").\n"
        "- Ein Vergleich mit einem frueheren Wert derselben Kennzahl (\"6 Prozent mehr als im\n"
        "  Vorjahr\", \"stieg auf 610 von 540 Millionen\") ist kein \"increases\"/\"decreases\"\n"
        "  zwischen zwei Kennzahlen oder zu einem Zeitpunkt: Unternehmen --reports--> Kennzahl\n"
        "  je Zeitpunkt (siehe oben), die Veraenderung steht im \"value\".\n"
        "- Kennzahlen sind keine Relationen (nicht \"growth\", \"valuation\", \"P/E\"): das\n"
        "  Unternehmen --reports--> die Kennzahl, der Wert steht in \"value\".\n"
        "- Angaben je Aktie oder je Einheit bleiben im \"value\" (\"2,10 je Aktie\"), auch wenn\n"
        "  die Waehrung in \"currency\" steht.\n"
        "- Tabellen: Die Zeilen stehen als \"Name | Wert | Wert\". Einheit und Zeitraum stehen im\n"
        "  Tabellenkopf (\"In millions\", \"Three Months Ended July 26, 2026\") und gehoeren in jedes\n"
        "  Tripel: \"value\" mit Einheit, die Zahl Ziffer fuer Ziffer wie in der Tabelle, Trennzeichen\n"
        "  nicht aendern (\"9,115\" unter \"In millions\" ergibt \"9,115 million\", nie \"9.115\"),\n"
        "  \"as_of\" mit dem Zeitraum der Spalte. Jede Spalte ist ein eigenes Tripel. Prozentzeilen und Angaben je\n"
        "  Aktie haben keine Millionen-Einheit. Ist die Spalte nicht eindeutig: Zeile weglassen.\n"
        "- Feste Namen fuer Kennzahlen: Gewinn je Aktie heisst \"Gewinn je Aktie\", die bereinigte\n"
        "  Zahl (non-GAAP, adjusted, normalized) \"bereinigter Gewinn je Aktie\" - nie nur \"Gewinn\",\n"
        "  auch wenn der Text das kurz so sagt. Umsatz heisst \"Umsatz\".\n"
        "- \"as_of\" nennt immer das Jahr, Quartale mit Geschaeftsjahr (\"Q3 Geschaeftsjahr 2026\").\n"
        "- Prognosen und Schaetzungen sind kein Bericht: Zahlen fuer die Zukunft oder von Analysten\n"
        "  ergeben \"forecasts\" (Wer schaetzt --forecasts--> Kennzahl, die Firma in \"condition\"),\n"
        "  nicht \"reports\", mit \"evidence_level\" Prognose oder Analystenschaetzung.\n"
        "- \"acquires\" nur fuer eine vollstaendige Uebernahme. Der Kauf von Anteilen ist\n"
        "  \"holds_stake_in\" mit der Hoehe in \"value\"; ist er nur geplant, \"plans\".\n"
        "- Verkauft oder reduziert jemand Anteile: Verkaeufer --sells_stake_in--> Firma, die Hoehe\n"
        "  in \"value\" (\"gesamte Beteiligung\", \"von 5 auf 3 Prozent\"), den genannten Grund in\n"
        "  \"condition\". Ein Verkauf ist nie \"holds_stake_in\".\n"
        "- Verneinte oder dementierte Aussagen: \"hob die Prognose nicht an\" ergibt Firma\n"
        "  --forecasts--> Prognose mit \"negated\": \"ja\". Nie als positive Aussage ablegen.\n"
        "- Nennt jemand eine eigene Verkaufsregel: Investor --plans--> Verkauf von Aktien, die\n"
        "  Bedingung in \"condition\".\n"
        "- Zentralbanken sind \"central_bank\", Ratingagenturen \"rating_agency\", nicht\n"
        "  \"company\". Setzt eine Zentralbank einen Zins fest oder laesst ihn unveraendert:\n"
        "  Zentralbank --sets--> Leitzins mit dem Stand in \"value\". Ein Rating: Agentur\n"
        "  --rates--> Bewertetes, Note und Richtung in \"value\" (\"BBB+, hochgestuft\").\n"
        "- Eine Person mit Funktion (\"Finanzvorstand Jan Weber\") ergibt Person\n"
        "  --employed_by--> Unternehmen, die Funktion in \"value\".\n"
        "- Nur Relationen aus der Liste der bekannten Relationen, keine neuen. Passt keine,\n"
        "  lass die Aussage weg, statt eine unpassende zu waehlen.\n"
        "- Typen: Aktienindizes (Dax, S&P 500, Nasdaq) sind \"index\"; Universitaeten,\n"
        "  Institute, Boersen und Gruppen wie Anleger oder Kunden \"organization\"; Technologien,\n"
        "  Verfahren und Anlagen \"technology\"; Nachfrage, Bewertung, Wachstum und Kennzahlen\n"
        "  \"financial_metric\"; Engpaesse, Abschwuenge und andere Vorgaenge \"event\"."
    ),
}

# Absichtlich nicht aus dem Eval-Text (polygraph evals/texts/zinsen_aktien.txt),
# sonst misst die Eval das Beispiel statt der Extraktion
EXAMPLE_TEXT = (
    "Die Allianz steigerte im zweiten Quartal 2024 ihren operativen Gewinn auf 3,8 Milliarden Euro, "
    "wie aus dem Quartalsbericht hervorgeht. Laut Analysten belastete die Zinserhoehung der Fed im "
    "Maerz 2022 die Aktienkurse im Tech-Sektor um durchschnittlich 8 Prozent."
)

EXAMPLE_OUTPUT = (
    {"subject": "Allianz", "subject_type": "company", "subject_type_is_new": False,
     "relation": "reports", "relation_is_new": False,
     "object": "operativer Gewinn", "object_type": "financial_metric", "object_type_is_new": False,
     "value": "3,8 Milliarden", "condition": None, "evidence_level": "Quartalsbericht",
     "as_of": "zweites Quartal 2024", "currency": "EUR", "confidence": 0.95},
    {"subject": "Zinserhoehung der Fed", "subject_type": "event", "subject_type_is_new": False,
     "relation": "triggers_decline_of", "relation_is_new": False,
     "object": "Aktienkurse im Tech-Sektor", "object_type": "financial_metric", "object_type_is_new": False,
     "value": "durchschnittlich 8 Prozent", "condition": "Tech-Sektor", "evidence_level": "Analystenschaetzung",
     "as_of": "Maerz 2022", "currency": None, "confidence": 0.8},
)


# Feste Knotennamen (Schreibweise klein -> Knoten). Im Graphen lag dieselbe Kennzahl unter
# 12 Namen, Besi unter zwei Knoten mit je 37 Kanten (2026-11-09). Bereinigte Zahlen bleiben
# getrennt: GAAP 8,66 und non-GAAP 9,42 sind zwei Kennzahlen desselben Jahres.
ALIASES = {
    **dict.fromkeys(("eps", "gaap eps", "diluted eps", "diluted earnings per share", "earnings per share: diluted",
                     "gewinn je aktie", "gewinn pro aktie"), "earnings per share"),
    **dict.fromkeys(("non-gaap eps", "adjusted eps", "normalized eps", "non-gaap earnings per share",
                     "non-gaap earnings per diluted share", "bereinigter gewinn je aktie"),
                    "adjusted earnings per share"),
    **dict.fromkeys(("net revenue", "net sales", "revenues", "total revenue", "umsatz"), "revenue"),
    **dict.fromkeys(("amat", "applied materials, inc.", "applied materials inc", "applied materials inc."),
                    "Applied Materials"),
    **dict.fromkeys(("besi", "be semiconductor", "be semiconductor industries", "be semiconductor industries nv"),
                    "BE Semiconductor Industries N.V."),
}


def _triple(subject, subject_type, relation, obj, object_type, confidence=0.9, **qualifiers):
    """Beispiel-Tripel mit allen Qualifiern des Profils (fehlende als None)."""
    return {"subject": subject, "subject_type": subject_type, "subject_type_is_new": False,
            "relation": relation, "relation_is_new": False,
            "object": obj, "object_type": object_type, "object_type_is_new": False,
            **{q.name: qualifiers.get(q.name) for q in QUALIFIERS}, "confidence": confidence}


# Nachrichten aller Art im Finanz-Graphen (2026-11-07): Erdbeben, Kriege, Wahlen
# oder Urteile sollen spaeter mit Kursbewegungen verknuepft werden. Allgemein
# gehalten statt je Nachrichtenart eigene Typen - alles, was passiert, ist ein
# "event", die Art steckt im Namen, die Rolle der Beteiligten in "condition".
# Die letzten sechs Typen sind die Bruecke zu den Finanzartikeln.
NEWS = Variant(
    description=(
        "Meldung, deren Hauptthema ein Geschehen ausserhalb der Wirtschaft im engeren Sinn ist:\n"
        "Katastrophe, Krieg, Anschlag, Wahl, Regierung, Gesetz, Urteil, Streik, Protest, Pandemie,\n"
        "Unfall, Gipfel, Sport, Preisverleihung (auch Nobelpreise), Personalie aus Politik oder\n"
        "Gesellschaft. Auch wenn am Rande ein Unternehmen, eine Strafe oder eine Reaktion der\n"
        "Maerkte vorkommt."),
    entity_types=(
        "event", "person", "organization", "country", "region", "position", "regulation", "award",
        "research_field", "company", "sector", "financial_metric", "index", "currency", "product",
    ),
    relation_types=(
        "occurred_in", "located_in", "part_of", "involved_in", "caused", "affected", "responded_to",
        "enacted", "applies_to", "won", "lost", "holds_position", "member_of", "employed_by",
        "awarded_to", "awarded_for", "increases", "decreases", "influences",
    ),
    extract_notes=(
        "- Ein Ereignis heisst nach Art, Ort und Jahr (\"Erdbeben in Taiwan 2026\",\n"
        "  \"Bundestagswahl 2025\"), das genaue Datum steht in \"as_of\". So trifft ein spaeterer\n"
        "  Artikel ueber dasselbe Ereignis denselben Namen.\n"
        "- Wer beteiligt ist: X --involved_in--> Ereignis, die Rolle in \"condition\"\n"
        "  (\"Angreifer\", \"Kandidat\", \"Klaeger\", \"Gastgeber\").\n"
        "- Folgen mit Zahl in \"value\": Ereignis --affected--> Betroffene, value \"14 Tote\".\n"
        "  Ursachen: \"caused\"; Reaktionen: X --responded_to--> Ereignis, value = die Massnahme.\n"
        "- Beschluesse: Regierung, Parlament oder Gericht --enacted--> Gesetz, Sanktion oder\n"
        "  Urteil (Typ \"regulation\"); Gesetz --applies_to--> wen es betrifft.\n"
        "- Ausgang: X --won/lost--> Wahl, Prozess oder Wettbewerb, Ergebnis in \"value\".\n"
        "- Aemter: Person --holds_position--> Amt (Typ \"position\"), Land oder Organisation in\n"
        "  \"condition\", seit wann in \"as_of\".\n"
        "- Preise: Preis --awarded_to--> Person, Preis --awarded_for--> Forschungsgebiet.\n"
        "- Wirkt das Ereignis auf Unternehmen, Branchen, Preise oder Kurse, gehoert die Richtung\n"
        "  in die Relation (\"increases\", \"decreases\"), der Betrag in \"value\".\n"
        "- Laender sind \"country\", Bundeslaender, Provinzen und Staedte \"region\"; Parteien,\n"
        "  Regierungen, Gerichte, Armeen, Gewerkschaften und Vereine \"organization\"."),
    example_text=(
        "Ein Erdbeben der Staerke 6,8 erschuetterte am 3. Maerz 2025 den Norden Chiles. Die "
        "Regierung rief den Notstand aus; mehrere Kupferminen stellten den Betrieb vorerst ein."),
    example_output=(
        _triple("Erdbeben in Chile 2025", "event", "occurred_in", "Chile", "country", 0.95,
                value="Staerke 6,8", condition="Norden", as_of="3. Maerz 2025"),
        _triple("Regierung von Chile", "organization", "responded_to", "Erdbeben in Chile 2025", "event",
                value="Notstand ausgerufen", as_of="Maerz 2025"),
        _triple("Erdbeben in Chile 2025", "event", "affected", "Kupferminen in Chile", "sector", 0.85,
                value="Betrieb vorerst eingestellt", as_of="Maerz 2025"),
    ),
)

# Reine Wissenschaft im Finanz-Graphen (2026-11-07): wie Nanotechnik,
# Halbleiter oder Batterien funktionieren, ohne Firmen und Kurse - damit
# spaetere Finanzartikel ueber dieselbe Technik daran anknuepfen.
SCIENCE = Variant(
    description=(
        "Erklaerender Text: wie eine Technik, ein Material oder ein physikalischer, chemischer\n"
        "oder biologischer Vorgang funktioniert und warum - ohne Unternehmenszahlen, Kurse oder\n"
        "Marktbewegungen. Eine Meldung darueber, wer etwas entdeckt oder einen Preis bekommen hat,\n"
        "ist \"news\"."),
    entity_types=(
        "technology", "material", "phenomenon", "process", "instrument", "research_field",
        "application", "person", "organization",
    ),
    relation_types=(
        "enables", "based_on", "consists_of", "part_of", "used_for", "produces", "causes",
        "increases", "decreases", "measured_with", "developed_by", "employed_by", "belongs_to_class",
    ),
    extract_notes=(
        "- Erklaerungen sind Tripel: \"A, weil B\" ergibt B --causes/enables--> A. Nur was der\n"
        "  Text als Zusammenhang sagt, nicht jedes Fachwort einzeln.\n"
        "- Wovon etwas abhaengt: X --increases/decreases--> Groesse, die Zahl in \"value\"\n"
        "  (\"um das Zehnfache\"), die Bedingung in \"condition\" (\"bei Raumtemperatur\").\n"
        "- Aufbau: X --consists_of--> Bestandteil; Teil --part_of--> Ganzes.\n"
        "- Wer etwas entwickelt oder entdeckt hat: X --developed_by--> Person oder Organisation,\n"
        "  das Jahr in \"as_of\"; Person --employed_by--> Institut.\n"
        "- Anwendung: Technik --used_for--> Anwendung (Typ \"application\").\n"
        "- \"evidence_level\": Experiment, Simulation, Theorie, Uebersichtsartikel - nur wenn\n"
        "  der Text es sagt.\n"
        "- Techniken und Verfahren sind \"technology\" oder \"process\", Stoffe \"material\",\n"
        "  beobachtbare Effekte und Eigenschaften \"phenomenon\", Geraete \"instrument\"."),
    example_text=(
        "Graphen besteht aus einer einzigen Lage Kohlenstoffatome. Weil sich Elektronen darin fast "
        "ohne Widerstand bewegen, eignet es sich fuer sehr schnelle Transistoren. Andre Geim und "
        "Konstantin Novoselov isolierten es 2004 an der Universitaet Manchester."),
    example_output=(
        _triple("Graphen", "material", "consists_of", "Kohlenstoffatome", "material", 0.95,
                condition="eine einzige Lage"),
        _triple("Graphen", "material", "enables", "schnelle Transistoren", "application", 0.85,
                condition="Elektronen bewegen sich fast ohne Widerstand"),
        _triple("Graphen", "material", "developed_by", "Andre Geim", "person", 0.9, as_of="2004",
                value="isoliert"),
        _triple("Andre Geim", "person", "employed_by", "Universitaet Manchester", "organization", 0.85,
                as_of="2004"),
    ),
)

PROFILE = DomainProfile("finance", QUALIFIERS, ENTITY_TYPES, RELATION_TYPES, prompt_notes=PROMPT_NOTES,
                        example_text=EXAMPLE_TEXT, example_output=EXAMPLE_OUTPUT,
                        edge_key_fields=("as_of", "condition", "negated"),
                        # Nach dem Neu-Import 51 eigene Relationen des Modells
                        # (performance_1m, growth, supports, ...), 254 Kanten
                        closed_relations=True,
                        # Nach den Argos-Importen 287 von 557 Knoten mit eigenen
                        # Typen (technology, demand, growth, Zacks Rank, ...)
                        closed_types=True,
                        variants={"news": NEWS, "science": SCIENCE},
                        aliases=ALIASES,
                        description=(
                            "Hauptthema Wirtschaft und Finanzen: Unternehmen und ihre Zahlen, Maerkte,\n"
                            "Kurse, Indizes, Zinsen, Notenbanken, Konjunktur, Rohstoff- und Energiepreise,\n"
                            "Beteiligungen, Analysten - auch wenn der Text ein Ereignis, Politik oder\n"
                            "Technik als Grund nennt."))
