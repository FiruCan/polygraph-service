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
        "  mit Einheit (z.B. \"4.25 percent\", \"minus 12 percent\", \"3.8 billion\").\n"
        "  Steht nichts im Text: null.")),
    Qualifier("condition", "condition", "Bedingung", description=(
        "Markt, Region, Segment oder Szenario, unter denen die Aussage gilt\n"
        "  (z.B. \"euro area\", \"electric vehicle segment\"). Zeitangaben gehoeren in \"as_of\".\n"
        "  Sonst: null.")),
    Qualifier("evidence_level", "evidence", "Belegart", description=(
        "Art des Belegs, nur falls im Text genannt (z.B. \"annual report\",\n"
        "  \"quarterly report\", \"analyst estimate\", \"forecast\", \"announcement\").\n"
        "  Sonst: null. Nicht raten.")),
    Qualifier("as_of", "as of", "Stichtag", description=(
        "Zeitpunkt oder Zeitraum, auf den sich die Aussage bezieht, aus dem Text\n"
        "  (z.B. \"July 2023\", \"Q2 fiscal 2024\", \"2021\"). Ist die Angabe relativ (\"heute\",\n"
        "  \"gestern\", \"seit Jahresbeginn\", \"drittes Quartal\" ohne Jahr) und steht unten ein\n"
        "  Erscheinungsdatum, ergaenze damit Datum bzw. Jahr (bei Erscheinungsdatum 2025-03-14:\n"
        "  \"heute\" -> \"2025-03-14\", \"seit Jahresbeginn\" -> \"since the start of 2025\").\n"
        "  Ohne Erscheinungsdatum nur uebersetzen (\"today\"). Nennt der Text keine Zeit: null - das\n"
        "  Erscheinungsdatum dann nicht einsetzen.")),
    Qualifier("currency", "currency", "Waehrung", translate=False, description=(
        "Waehrung eines Betrags in \"value\" als ISO-Code (z.B. \"EUR\" fuer Euro,\n"
        "  \"USD\" fuer US-Dollar), nur wenn der Text sie nennt. Sonst: null."),
              pattern="^[A-Z]{3}$"),
    # Ein Tripel kann nur etwas behaupten: "hob die Prognose nicht an" blieb sonst dem Zufall ueberlassen
    # (2026-11-09: 4 von 2320 Kanten mit Verneinung, und nur als Wort im value)
    Qualifier("negated", "negated", "verneint", translate=False, description=(
        "Nur \"ja\" (fester Wert, nicht uebersetzen), wenn der Text die Aussage des Tripels verneint oder dementiert\n"
        "  (\"hob die Prognose nicht an\", \"dementierte die Uebernahme\"). Sonst: null."),
              pattern="^ja$"),
)

# technology und organization: im Graphen 122 Knoten "technology" (chip
# packaging, Hybrid Bonding) und 40 Universitaeten, Institute und Boersen
# ohne passenden Profil-Typ (2026-11-07). index: ohne ihn fehlte mit festen
# Typen der Dax-Schlusskurs (Eval holdout_marktbericht). fund: ETFs standen
# als index, product oder organization im Graphen, die Knotenwahl nahm den
# ETF SOXX fuer den Halbleiterindex SOX (O'Neil-Paket, 2026-11-11)
ENTITY_TYPES = (
    "company", "sector", "person", "financial_metric", "event", "regulation", "product",
    "central_bank", "rating_agency", "currency", "technology", "organization", "index", "fund",
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
        "  Eine Schaetzung steht oft unter dem Namen ihres Anbieters, als \"analyst consensus\" oder als\n"
        "  \"Consensus Estimate\" im Subjekt (\"... Consensus Estimate --forecasts--> earnings per share\"):\n"
        "  Sie gilt fuer die Firma in \"condition\", fehlt dort eine, fuer die Firma, um die es in den\n"
        "  Tripeln daneben geht. Fehlt sie nur fuer einige Quartale, vergleiche die Quartale, fuer die\n"
        "  es sie gibt.\n"
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
    # Geschaeftsjahr und Analystenkonsens (O'Neil-Paket, 2026-11-11): Jahreswerte
    # standen als "twelve months ended ...", Neunmonatswerte nur mit dem Jahr;
    # Schaetzungen hingen unter "analysts", "Wall Street consensus estimates",
    # "TIKR's October 19 consensus snapshot" ..., fast nie mit der Firma
    "extract": (
        "- Subjekt einer Kennzahl (revenue, EBIT, margin, dividend, stock price, yield) ist das\n"
        "  Unternehmen, der Markt oder das Wertpapier, dem sie gehoert - nie die Kennzahl selbst.\n"
        "  \"Der Umsatz sank um 8 Prozent\" in einem Text ueber Henkel ergibt Henkel --reports--> revenue.\n"
        "  Ebenso Aktienkurs und Boersenwert: \"Die Aktie von Henkel stieg um 2 Prozent auf 80 Euro\"\n"
        "  ergibt Henkel --reports--> stock price (value \"up 2 percent to 80\"), nicht\n"
        "  share --> price und nicht Henkel --increases--> share.\n"
        "- Nennt der Text fuer dieselbe Kennzahl Werte zu mehreren Zeitpunkten (aktuell und\n"
        "  Vorjahr, alte und neue Prognose), erzeuge je Zeitpunkt ein eigenes Tripel mit eigenem\n"
        "  \"as_of\". Ein relativer Zeitpunkt (\"Vorjahresquartal\") wird ausgeschrieben, wenn der\n"
        "  Text ihn eindeutig macht (\"Q3 2023\" neben \"Q3 2024\").\n"
        "- Wirkt etwas auf eine andere Groesse (Zinsen auf Kurse, Nachfrage auf Gewinn), gehoert\n"
        "  die Richtung in die Relation: \"increases\" bzw. \"decreases\" statt \"affects_metric\"\n"
        "  oder \"influences\". Veraendert sich eine eigene Kennzahl des Subjekts (\"Henkel verlor\n"
        "  8 Prozent Umsatz\"), ist das \"reports\" mit der Richtung im \"value\" (\"minus 8 percent\").\n"
        "- Ein Vergleich mit einem frueheren Wert derselben Kennzahl (\"6 Prozent mehr als im\n"
        "  Vorjahr\", \"stieg auf 610 von 540 Millionen\") ist kein \"increases\"/\"decreases\"\n"
        "  zwischen zwei Kennzahlen oder zu einem Zeitpunkt: Unternehmen --reports--> Kennzahl\n"
        "  je Zeitpunkt (siehe oben), die Veraenderung steht im \"value\".\n"
        "- Kennzahlen sind keine Relationen (nicht \"growth\", \"valuation\", \"P/E\"): das\n"
        "  Unternehmen --reports--> die Kennzahl, der Wert steht in \"value\".\n"
        "- Angaben je Aktie oder je Einheit bleiben im \"value\" (\"2.10 per share\"), auch wenn\n"
        "  die Waehrung in \"currency\" steht.\n"
        "- Tabellen: Die Zeilen stehen als \"Name | Wert | Wert\". Einheit und Zeitraum stehen im\n"
        "  Tabellenkopf (\"In millions\", \"Three Months Ended July 26, 2026\") und gehoeren in jedes\n"
        "  Tripel: \"value\" mit Einheit, die Zahl Ziffer fuer Ziffer wie in der Tabelle, Trennzeichen\n"
        "  nicht aendern (\"9,115\" unter \"In millions\" ergibt \"9,115 million\", nie \"9.115\"),\n"
        "  \"as_of\" mit dem Zeitraum der Spalte. Jede Spalte ist ein eigenes Tripel. Prozentzeilen und Angaben je\n"
        "  Aktie haben keine Millionen-Einheit. Ist die Spalte nicht eindeutig: Zeile weglassen.\n"
        "- Feste Namen fuer Kennzahlen: Gewinn je Aktie heisst \"earnings per share\", die bereinigte\n"
        "  Zahl (non-GAAP, adjusted, normalized) \"adjusted earnings per share\" - nie nur \"earnings\",\n"
        "  auch wenn der Text das kurz so sagt. Umsatz (sales, net sales) heisst \"revenue\", der\n"
        "  Aktienkurs \"stock price\".\n"
        "- Zeitraeume stehen nie im Namen von Subjekt oder Objekt (nicht \"revenue fiscal 2027\",\n"
        "  \"estimates for 2026\"), sondern in \"as_of\": Objekt \"revenue\", \"as_of\" \"fiscal 2027\".\n"
        "- \"as_of\" nennt immer das Jahr, Quartale mit Geschaeftsjahr (\"Q3 fiscal 2026\").\n"
        "  Ein ganzes Geschaeftsjahr (\"Geschaeftsjahr 2025\", \"full year\", \"twelve months ended ...\")\n"
        "  heisst \"fiscal 2025\"; sechs oder neun Monate heissen so (\"first nine months of fiscal\n"
        "  2026\") - nie nur das Jahr, sonst gilt ein Neunmonatswert als Jahreswert.\n"
        "- Prognosen und Schaetzungen sind kein Bericht: Zahlen fuer die Zukunft oder von Analysten\n"
        "  ergeben \"forecasts\" (Wer schaetzt --forecasts--> Kennzahl), nicht \"reports\", mit\n"
        "  \"evidence_level\" \"forecast\" oder \"analyst estimate\". \"condition\" nennt immer die Firma,\n"
        "  fuer die geschaetzt wird (\"for Henkel\"), auch wenn sie nur im Satz davor steht. Der\n"
        "  Durchschnitt vieler Analysten (Konsens, \"Wall Street erwartet\", consensus estimate) heisst\n"
        "  immer \"analyst consensus\", ein Datendienst, der ihn liefert, steht in \"evidence_level\".\n"
        "- \"acquires\" nur fuer eine vollstaendige Uebernahme. Der Kauf von Anteilen ist\n"
        "  \"holds_stake_in\" mit der Hoehe in \"value\"; ist er nur geplant, \"plans\".\n"
        "- Verkauft oder reduziert jemand Anteile: Verkaeufer --sells_stake_in--> Firma, die Hoehe\n"
        "  in \"value\" (\"entire stake\", \"from 5 to 3 percent\"), den genannten Grund in\n"
        "  \"condition\". Ein Verkauf ist nie \"holds_stake_in\".\n"
        "- Verneinte oder dementierte Aussagen: \"hob die Prognose nicht an\" ergibt Firma\n"
        "  --forecasts--> forecast mit \"negated\": \"ja\". Nie als positive Aussage ablegen.\n"
        "- Nennt jemand eine eigene Verkaufsregel: Investor --plans--> sale of shares, die\n"
        "  Bedingung in \"condition\".\n"
        "- Zentralbanken sind \"central_bank\", Ratingagenturen \"rating_agency\", nicht\n"
        "  \"company\". Setzt eine Zentralbank einen Zins fest oder laesst ihn unveraendert:\n"
        "  Zentralbank --sets--> key interest rate mit dem Stand in \"value\". Ein Rating: Agentur\n"
        "  --rates--> Bewertetes, Note und Richtung in \"value\" (\"BBB+, upgraded\").\n"
        "- Eine Person mit Funktion (\"Finanzvorstand Jan Weber\") ergibt Person\n"
        "  --employed_by--> Unternehmen, die Funktion in \"value\" (\"chief financial officer\").\n"
        "- Nur Relationen aus der Liste der bekannten Relationen, keine neuen. Passt keine,\n"
        "  lass die Aussage weg, statt eine unpassende zu waehlen.\n"
        "- Typen: Aktienindizes (Dax, S&P 500, Nasdaq) sind \"index\"; ETFs, Investmentfonds und\n"
        "  Vermoegensverwalter \"fund\", auch ein ETF, der einen Index abbildet; Universitaeten,\n"
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

def _triple(subject, subject_type, relation, obj, object_type, confidence=0.9, **qualifiers):
    """Beispiel-Tripel mit allen Qualifiern des Profils (fehlende als None)."""
    return {"subject": subject, "subject_type": subject_type, "subject_type_is_new": False,
            "relation": relation, "relation_is_new": False,
            "object": obj, "object_type": object_type, "object_type_is_new": False,
            **{q.name: qualifiers.get(q.name) for q in QUALIFIERS}, "confidence": confidence}


# Wie die Regeln oben: Quartal mit Geschaeftsjahr, die Richtung in "decreases" statt
# triggers_decline_of, der Sektor in "condition" statt im Namen. Das Modell folgte dem
# Beispiel ("zweites Quartal 2024") eher als der Regel. Deutscher Text, englische
# Tripel: der Graph ist komplett englisch, polygraph extrahiert gleich so (2026-11-18).
EXAMPLE_OUTPUT = (
    _triple("Allianz", "company", "reports", "operating profit", "financial_metric", 0.95,
            value="3.8 billion", evidence_level="quarterly report", as_of="Q2 fiscal 2024",
            currency="EUR"),
    _triple("Fed rate hike", "event", "decreases", "stock prices", "financial_metric", 0.8,
            value="8 percent on average", condition="tech sector", evidence_level="analyst estimate",
            as_of="March 2022"),
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
    # sales: 18 Kanten neben 134 unter revenue (2026-11-09), fast alle Umsatzzahlen
    **dict.fromkeys(("net revenue", "net revenues", "net sales", "revenues", "total revenue", "total revenues",
                     "sales", "turnover", "umsatz", "umsatzerloese", "umsatzerlöse"), "revenue"),
    **dict.fromkeys(("share price", "stock prices", "share prices", "aktienkurs", "aktienkurse"), "stock price"),
    # Die Extraktion nennt den Durchschnitt der Analysten "Analystenkonsens" (extract-Regel), uebersetzt
    # hiess er mal so, mal anders - im Graphen lag er unter 13 Namen (2026-11-09)
    **dict.fromkeys(("analystenkonsens", "analysts' consensus", "analyst consensus estimate",
                     "analyst consensus estimates", "consensus", "consensus estimate", "consensus estimates",
                     "wall street consensus", "wall street consensus estimate", "wall street consensus estimates",
                     "street consensus"), "analyst consensus"),
    **dict.fromkeys(("amat", "applied materials, inc.", "applied materials inc", "applied materials inc."),
                    "Applied Materials"),
    **dict.fromkeys(("besi", "be semiconductor", "be semiconductor industries", "be semiconductor industries nv"),
                    "BE Semiconductor Industries N.V."),
}


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
        "- Ein Ereignis heisst nach Art, Ort und Jahr (\"earthquake in Taiwan 2026\",\n"
        "  \"German federal election 2025\", \"ransomware attack on Nordhafen 2026\"), das genaue\n"
        "  Datum steht in \"as_of\". So trifft ein spaeterer Artikel ueber dasselbe Ereignis, in\n"
        "  welcher Sprache auch immer, denselben Namen.\n"
        "- Wer beteiligt ist: X --involved_in--> Ereignis, die Rolle in \"condition\"\n"
        "  (\"attacker\", \"candidate\", \"plaintiff\", \"host\").\n"
        "- Folgen mit Zahl in \"value\": Ereignis --affected--> Betroffene, value \"14 dead\".\n"
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
        _triple("earthquake in Chile 2025", "event", "occurred_in", "Chile", "country", 0.95,
                value="magnitude 6.8", condition="north", as_of="2025-03-03"),
        _triple("government of Chile", "organization", "responded_to", "earthquake in Chile 2025", "event",
                value="declared a state of emergency", as_of="March 2025"),
        _triple("earthquake in Chile 2025", "event", "affected", "copper mines in Chile", "sector", 0.85,
                value="operations suspended for now", as_of="March 2025"),
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
        "  (\"tenfold\"), die Bedingung in \"condition\" (\"at room temperature\").\n"
        "- Aufbau: X --consists_of--> Bestandteil; Teil --part_of--> Ganzes.\n"
        "- Wer etwas entwickelt oder entdeckt hat: X --developed_by--> Person oder Organisation,\n"
        "  das Jahr in \"as_of\"; Person --employed_by--> Institut.\n"
        "- Anwendung: Technik --used_for--> Anwendung (Typ \"application\").\n"
        "- \"evidence_level\": experiment, simulation, theory, review - nur wenn\n"
        "  der Text es sagt.\n"
        "- Techniken und Verfahren sind \"technology\" oder \"process\", Stoffe \"material\",\n"
        "  beobachtbare Effekte und Eigenschaften \"phenomenon\", Geraete \"instrument\"."),
    example_text=(
        "Graphen besteht aus einer einzigen Lage Kohlenstoffatome. Weil sich Elektronen darin fast "
        "ohne Widerstand bewegen, eignet es sich fuer sehr schnelle Transistoren. Andre Geim und "
        "Konstantin Novoselov isolierten es 2004 an der Universitaet Manchester."),
    example_output=(
        _triple("graphene", "material", "consists_of", "carbon atoms", "material", 0.95,
                condition="a single layer"),
        _triple("graphene", "material", "enables", "fast transistors", "application", 0.85,
                condition="electrons move almost without resistance"),
        _triple("graphene", "material", "developed_by", "Andre Geim", "person", 0.9, as_of="2004",
                value="isolated"),
        _triple("Andre Geim", "person", "employed_by", "University of Manchester", "organization", 0.85,
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
