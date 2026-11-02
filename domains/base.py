"""
base.py
-------
Was ein Domaenen-Profil festlegt (DomainProfile): welche Angaben an den
Kanten es gibt (Qualifier, z.B. evidence_level in der Medizin, as_of und
currency an der Boerse), mit welchem Vokabular die Extraktion startet und
welche fachlichen Hinweise in die Prompts kommen (prompt_notes). Der Kern (graph/) kennt keine Domaene, er fragt nur das Profil
seines Graphen (domains.profile_of).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Qualifier:
    """
    Eine Angabe an der Kante neben relation, confidence und origin.
    label: Kurzname in den Prompts von /ask ("evidence"), label_de: in den
    Prompts der Fragevorschlaege ("Evidenz"). translate: Freitext aus dem
    Quelltext, der beim Import ins Englische uebersetzt wird (graph/translate.py)
    - ein Waehrungscode braucht das nicht. description: Regel fuer die
    Extraktion in polygraph (GET /profile), steht dort woertlich als
    '- "<name>": <description>' im Prompt - Zeilenumbrueche mit zwei
    Leerzeichen Einzug wie in polygraph prompts/extract.md. pattern: Regex,
    die polygraph ins JSON-Schema der Extraktion setzt (Ollama haelt sie ein,
    z.B. "^[A-Z]{3}$" fuer einen Waehrungscode); leer: beliebiger Text.
    """
    name: str
    label: str
    label_de: str
    translate: bool = True
    description: str = ""
    pattern: str = ""


@dataclass(frozen=True)
class DomainProfile:
    name: str
    qualifiers: tuple
    entity_types: tuple = ()
    relation_types: tuple = ()
    type_parents: dict = field(default_factory=dict)
    # Prompt -> fachliche Hinweise: "answer" (ask_answer.md), "check"
    # (ask_check.md), "suggest" (suggest_questions.md), "extract" (in polygraph
    # prompts/extract.md, ueber GET /profile)
    prompt_notes: dict = field(default_factory=dict)
    # Beispiel fuer den Extraktions-Prompt in polygraph: ein Text und die
    # Tripel daraus, mit allen Qualifiern des Profils
    example_text: str = ""
    example_output: tuple = ()
    # Qualifier, die eine Aussage von einer gleichlautenden unterscheiden:
    # dieselbe Kennzahl einer Quelle fuer Q3 2024 und das Vorjahresquartal
    # sind zwei Kanten, nicht eine, die die andere ueberschreibt
    # (GraphStore._find_edge_key). Leer: Relation + Quelle wie bisher.
    edge_key_fields: tuple = ()
    # Nur die Relationen des Profils: polygraph setzt sie als feste Liste ins
    # JSON-Schema, das Modell kann keine eigenen mehr erfinden und haeufige
    # Begriffe aus dem Graphen kommen nicht dazu. Aus: wie bisher, neue
    # Relationen moeglich (relation_is_new).
    closed_relations: bool = False

    @property
    def qualifier_fields(self) -> tuple:
        return tuple(q.name for q in self.qualifiers)

    @property
    def detail_fields(self) -> tuple:
        """Kanten-Felder mit Freitext, die beim Import uebersetzt werden."""
        return tuple(q.name for q in self.qualifiers if q.translate)

    def notes(self, prompt: str) -> str:
        """
        Block fuer den Platzhalter {domain_notes} im Prompt - leer, wenn das
        Profil fuer diesen Prompt nichts hat; der Prompt ist dann genau der
        allgemeine.
        """
        text = self.prompt_notes.get(prompt, "").strip()
        return f"\n\nHINWEISE ZUM FACHGEBIET:\n{text}" if text else ""

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "qualifiers": [{"name": q.name, "label": q.label, "label_de": q.label_de,
                            "translate": q.translate, "description": q.description,
                            "pattern": q.pattern}
                           for q in self.qualifiers],
            "entity_types": list(self.entity_types),
            "relation_types": list(self.relation_types),
            "type_parents": dict(sorted(self.type_parents.items())),
            "example_text": self.example_text,
            "example_output": list(self.example_output),
            # Fachregeln fuer den Extraktions-Prompt in polygraph ({domain_notes}
            # in prompts/extract.md), roh - polygraph setzt die Ueberschrift
            "extract_notes": self.prompt_notes.get("extract", "").strip(),
            "closed_relations": self.closed_relations,
        }
