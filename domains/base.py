"""
base.py
-------
Was ein Domaenen-Profil festlegt (DomainProfile): welche Angaben an den
Kanten es gibt (Qualifier, z.B. evidence_level in der Medizin, spaeter
as_of/currency an der Boerse) und mit welchem Vokabular die Extraktion
startet. Der Kern (graph/) kennt keine Domaene, er fragt nur das Profil
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
    - ein Datum oder ein Waehrungscode braucht das nicht.
    """
    name: str
    label: str
    label_de: str
    translate: bool = True


@dataclass(frozen=True)
class DomainProfile:
    name: str
    qualifiers: tuple
    entity_types: tuple = ()
    relation_types: tuple = ()
    type_parents: dict = field(default_factory=dict)

    @property
    def qualifier_fields(self) -> tuple:
        return tuple(q.name for q in self.qualifiers)

    @property
    def detail_fields(self) -> tuple:
        """Kanten-Felder mit Freitext, die beim Import uebersetzt werden."""
        return tuple(q.name for q in self.qualifiers if q.translate)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "qualifiers": [{"name": q.name, "label": q.label, "translate": q.translate}
                           for q in self.qualifiers],
            "entity_types": list(self.entity_types),
            "relation_types": list(self.relation_types),
            "type_parents": dict(sorted(self.type_parents.items())),
        }
