"""
generic.py
----------
Profil ohne Fachgebiet: das Verhalten vor den Domaenen-Profilen. Gilt fuer
eine neue Instanz ohne POLYGRAPH_DOMAIN und fuer einen alten Graphen, dem
noch kein Profil zugewiesen wurde. Das Startvokabular ist das von polygraph
(configs/start_vocabulary.json), ebenso das Beispiel und die Feldregeln
(prompts/extract.md) - so bleibt der Extraktions-Prompt fuer diese Profile
genau der bisherige.
"""

from domains.base import DomainProfile, Qualifier

QUALIFIERS = (
    Qualifier("value", "value", "Wert", description=(
        "Zahlen und Effektgroessen, die die Beziehung quantifizieren,\n"
        "  woertlich mit Einheit (z.B. \"15 bis 20 Prozent\"). Steht nichts im Text: null.")),
    Qualifier("condition", "condition", "Bedingung", description=(
        "Dosis, Menge, Haeufigkeit, Gruppe, Ort oder Zeitraum, unter\n"
        "  denen die Aussage gilt (z.B. \"1-2 Einheiten pro Woche, Erwachsene\",\n"
        "  \"Maerz 2022, USA\"). Sonst: null.")),
    Qualifier("evidence_level", "evidence", "Evidenz", description=(
        "Art des Belegs, nur falls im Text genannt (z.B. \"RCT\",\n"
        "  \"Kohortenstudie\", \"Meta-Analyse\", \"Beobachtungsstudie\", \"Analystenschaetzung\").\n"
        "  Sonst: null. Nicht raten.")),
)

ENTITY_TYPES = (
    "person", "organization", "location", "event", "study", "population", "concept",
    "process", "method", "product", "substance", "metric", "condition", "structure", "activity",
)

RELATION_TYPES = (
    "causes", "increases", "reduces", "influences", "correlates_with", "does_not_affect",
    "is_type_of", "is_part_of", "contains", "produces", "uses", "used_for", "precedes",
    "located_in", "member_of", "studied_in",
)

EXAMPLE_TEXT = (
    "In einer randomisierten Studie senkte Metformin (850 mg zweimal taeglich) bei Erwachsenen mit "
    "Praediabetes das Risiko fuer Typ-II-Diabetes um 31 Prozent. Laut Analysten belastete die "
    "Zinserhoehung der Fed im Maerz 2022 die Aktienkurse im Tech-Sektor um durchschnittlich 8 Prozent."
)

EXAMPLE_OUTPUT = (
    {"subject": "Metformin", "subject_type": "substance", "subject_type_is_new": False,
     "relation": "reduces_risk_of", "relation_is_new": True,
     "object": "Typ-II-Diabetes", "object_type": "disease", "object_type_is_new": True,
     "value": "31 Prozent", "condition": "850 mg zweimal taeglich, Erwachsene mit Praediabetes",
     "evidence_level": "RCT", "confidence": 0.95},
    {"subject": "Zinserhoehung der Fed", "subject_type": "event", "subject_type_is_new": False,
     "relation": "reduces", "relation_is_new": False,
     "object": "Aktienkurse im Tech-Sektor", "object_type": "metric", "object_type_is_new": False,
     "value": "durchschnittlich 8 Prozent", "condition": "Maerz 2022",
     "evidence_level": "Analystenschaetzung", "confidence": 0.8},
)

PROFILE = DomainProfile("generic", QUALIFIERS, ENTITY_TYPES, RELATION_TYPES,
                        example_text=EXAMPLE_TEXT, example_output=EXAMPLE_OUTPUT)
