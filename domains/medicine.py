"""
medicine.py
-----------
Profil Medizin. Neben value, condition und evidence_level eigene Angaben fuer
das, was in der Medizin am haeufigsten bestimmt, wofuer eine Aussage gilt:
population (welche Menschen), model (Tiermodell oder Zellkultur statt
Mensch), dose und duration. Grundlage: Probelauf ueber die 1.997 Bedingungen
des Medizin-Graphen (2026-10-31) - ein Drittel nannte eine Patientengruppe,
je rund ein Zehntel Dauer, Studienmodell oder Studiendesign; Letzteres stand
in "condition" statt in "evidence_level". "condition" bleibt fuer den Rest
(Ort im Koerper, Zustand, Voraussetzung, Land oder Region).

Der Bestand ist umgestellt (2026-11-02, aus der Zerlegung des Probelaufs):
1.163 der 1.996 Kanten mit "condition" haben ihre Teile jetzt in den neuen
Feldern.
"""

from domains import generic
from domains.base import DomainProfile, Qualifier

QUALIFIERS = (
    generic.QUALIFIERS[0],  # value
    Qualifier("population", "population", "Gruppe", description=(
        "Fuer welche Menschen die Aussage gilt: Patientengruppe, Alter, Geschlecht,\n"
        "  Erkrankung mit Verlaufsform oder Schweregrad (z.B. \"adults with prediabetes\",\n"
        "  \"children\", \"relapsing MS\", \"EDSS 7.0 and above\"). Tiere und Zellkulturen gehoeren\n"
        "  in \"model\". Sonst: null.")),
    Qualifier("model", "model", "Modell", description=(
        "Studienmodell, wenn die Aussage nicht an Menschen gezeigt wurde: Tierart,\n"
        "  Tiermodell, Zellkultur, in vitro (z.B. \"mice\", \"EAE mouse model\", \"in vitro\").\n"
        "  An Menschen oder nicht genannt: null.")),
    Qualifier("dose", "dose", "Dosis", description=(
        "Wie eine Massnahme angewendet wird: Dosis, Haeufigkeit, Intensitaet,\n"
        "  Darreichungsform, Dauer einer einzelnen Einheit (z.B. \"850 mg twice daily\",\n"
        "  \"oral\", \"five times a week, 30 minutes\"). Sonst: null.")),
    Qualifier("duration", "duration", "Dauer", description=(
        "Wie lange oder in welchem Zeitfenster: Behandlungs- oder Beobachtungsdauer,\n"
        "  Lebens- oder Krankheitsphase, in der etwas wirkt (z.B. \"three years\",\n"
        "  \"within 24 weeks\", \"in childhood\", \"during a relapse\").\n"
        "  Sonst: null.")),
    Qualifier("condition", "condition", "Bedingung", description=(
        "Weitere Umstaende, unter denen die Aussage gilt: Ort im Koerper, Zustand,\n"
        "  Voraussetzung, Land oder Region (z.B. \"in the white matter\", \"with preserved\n"
        "  axons\", \"in the EU\").\n"
        "  Gruppe, Modell, Dosis, Dauer und Studiendesign stehen in ihren eigenen Feldern,\n"
        "  nicht hier. Sonst: null.")),
    Qualifier("evidence_level", "evidence", "Evidenz", description=(
        "Studiendesign, nur falls im Text genannt (z.B. \"RCT\", \"cohort study\",\n"
        "  \"meta-analysis\", \"case report\", \"phase II trial\", \"animal study\").\n"
        "  Sonst: null. Nicht raten.")),
)

PROMPT_NOTES = {
    # Aus dem Probelauf: Mechanismen, Richtungen und Endpunkte standen in
    # "condition" (IL-15 --contributes_to--> neural damage mit "by enhancing
    # CD8+ T cell cytotoxicity"; complications --causes--> life expectancy mit
    # "decreased"). Beispiele absichtlich nicht aus diesen Kanten.
    "extract": (
        "- Sagt der Text, wie etwas wirkt (\"indem es X anregt\", \"ueber X\"), erzeuge dafuer\n"
        "  eigene Tripel (A --increases--> X, X --increases--> B) statt den Weg in \"condition\"\n"
        "  zu schreiben.\n"
        "- Die Richtung gehoert in die Relation: \"reduces\" statt \"causes\" mit \"decreased\"\n"
        "  in \"condition\".\n"
        "- Das Objekt ist die Groesse, auf die gewirkt wird (\"relapse rate\"), nicht ein\n"
        "  Oberbegriff mit dem eigentlichen Ziel in \"condition\"."
    ),
    "answer": (
        "- Hat ein Tripel ein Studienmodell (model: z.B. Maeuse, in vitro), sag das ausdruecklich:\n"
        "  der Befund gilt dort, nicht nachgewiesen fuer Menschen.\n"
        "- Nennt ein Tripel eine Gruppe (population), Dosis (dose) oder Dauer (duration),\n"
        "  nimm sie in den Satz auf, statt die Aussage zu verallgemeinern."
    ),
    "check": (
        "- Stellt ein Satz einen Befund aus einem Studienmodell (model) als Befund an Menschen\n"
        "  dar, oder verallgemeinert er ueber die Gruppe (population) des Tripels hinaus, ist er\n"
        "  hoechstens \"teilweise\"."
    ),
    "suggest": (
        "- Hat ein Fakt ein Studienmodell, eine Gruppe oder eine Dosis, greife sie in der Frage\n"
        "  auf (z.B. \"bei Maeusen\", \"bei Kindern\")."
    ),
}

# Absichtlich nicht aus dem Eval-Text (polygraph evals/texts/ms_therapie.txt).
# Deutscher Text, englische Tripel: der Graph ist komplett englisch (2026-11-18)
EXAMPLE_TEXT = (
    "In einer randomisierten Studie senkte Metformin (850 mg zweimal taeglich) bei Erwachsenen mit "
    "Praediabetes das Risiko fuer Typ-II-Diabetes innerhalb von drei Jahren um 31 Prozent. Bei Ratten "
    "verbesserte Ausdauertraining (fuenfmal pro Woche, 30 Minuten) die Insulinempfindlichkeit, indem es "
    "die Zahl der Mitochondrien im Muskel erhoehte."
)

_NONE = {"value": None, "population": None, "model": None, "dose": None, "duration": None,
         "condition": None, "evidence_level": None}

EXAMPLE_OUTPUT = (
    {"subject": "Metformin", "subject_type": "substance", "subject_type_is_new": False,
     "relation": "reduces_risk_of", "relation_is_new": True,
     "object": "type 2 diabetes", "object_type": "disease", "object_type_is_new": True,
     **_NONE, "value": "31 percent", "population": "adults with prediabetes",
     "dose": "850 mg twice daily", "duration": "three years", "evidence_level": "RCT",
     "confidence": 0.95},
    {"subject": "endurance training", "subject_type": "activity", "subject_type_is_new": False,
     "relation": "increases", "relation_is_new": False,
     "object": "insulin sensitivity", "object_type": "metric", "object_type_is_new": False,
     **_NONE, "model": "rats", "dose": "five times a week, 30 minutes", "confidence": 0.85},
    {"subject": "endurance training", "subject_type": "activity", "subject_type_is_new": False,
     "relation": "increases", "relation_is_new": False,
     "object": "number of mitochondria", "object_type": "metric", "object_type_is_new": False,
     **_NONE, "model": "rats", "dose": "five times a week, 30 minutes", "condition": "in muscle",
     "confidence": 0.85},
    {"subject": "number of mitochondria", "subject_type": "metric", "subject_type_is_new": False,
     "relation": "increases", "relation_is_new": False,
     "object": "insulin sensitivity", "object_type": "metric", "object_type_is_new": False,
     **_NONE, "model": "rats", "confidence": 0.8},
)

# Dieselbe Aussage einer Quelle fuer Erwachsene und fuer Kinder, an Maeusen und
# an Menschen sind zwei Kanten. "condition" bewusst nicht: der Bestand hat dort
# noch alles Gemischte, und eine Quelle aktualisiert ihre Kante wie bisher.
PROFILE = DomainProfile("medicine", QUALIFIERS, generic.ENTITY_TYPES, generic.RELATION_TYPES,
                        prompt_notes=PROMPT_NOTES, example_text=EXAMPLE_TEXT, example_output=EXAMPLE_OUTPUT,
                        edge_key_fields=("population", "model", "dose", "duration"))
