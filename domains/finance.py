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

from domains.base import DomainProfile, Qualifier

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
        "Zeitpunkt oder Zeitraum, auf den sich die Aussage bezieht, woertlich\n"
        "  aus dem Text (z.B. \"Juli 2023\", \"zweites Quartal 2024\", \"2021\"). Sonst: null.\n"
        "  Nicht raten - auch nicht aus dem Erscheinungsdatum des Artikels.")),
    Qualifier("currency", "currency", "Waehrung", translate=False, description=(
        "Waehrung eines Betrags in \"value\" als ISO-Code (z.B. \"EUR\" fuer Euro,\n"
        "  \"USD\" fuer US-Dollar), nur wenn der Text sie nennt. Sonst: null.")),
)

ENTITY_TYPES = (
    "company", "sector", "person", "financial_metric", "event", "regulation", "product",
)

RELATION_TYPES = (
    "influences", "competes_with", "reports", "acquires", "affects_metric", "employed_by",
    "increases_risk_of", "triggers_decline_of", "correlates_with", "belongs_to_class",
    "regulated_by",
)

PROMPT_NOTES = {
    "answer": (
        "- Kurse, Zinsen und Kennzahlen gelten nur zu einem Zeitpunkt: nenne den Stichtag\n"
        "  (as of) und die Waehrung (currency), wenn das Tripel sie hat. Fehlt der Stichtag,\n"
        "  sag, dass offen ist, wann der Wert galt.\n"
        "- Keine Anlageempfehlung und keine Kursprognose ueber die Tripel hinaus - auch\n"
        "  nicht im Abschnitt mit der Vermutung."
    ),
    "check": (
        "- Stichtag (as of) und Waehrung (currency): nennt ein Satz einen Wert mit einem\n"
        "  anderen Zeitpunkt oder einer anderen Waehrung als das Tripel, oder macht er einen\n"
        "  Wert ohne Stichtag zum heutigen Stand, ist er hoechstens \"teilweise\".\n"
        "- Eine Anlageempfehlung oder Kursprognose ist nie \"gedeckt\"."
    ),
    "suggest": (
        "- Hat ein Fakt einen Stichtag, greife ihn in der Frage auf (z.B. \"im Juli 2023\").\n"
        "- Keine Fragen nach Kaufempfehlungen oder kuenftigen Kursen."
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

PROFILE = DomainProfile("finance", QUALIFIERS, ENTITY_TYPES, RELATION_TYPES, prompt_notes=PROMPT_NOTES,
                        example_text=EXAMPLE_TEXT, example_output=EXAMPLE_OUTPUT)
