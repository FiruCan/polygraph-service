"""
generic.py
----------
Profil ohne Fachgebiet: das Verhalten vor den Domaenen-Profilen. Gilt fuer
eine neue Instanz ohne POLYGRAPH_DOMAIN und fuer einen alten Graphen, dem
noch kein Profil zugewiesen wurde. Das Startvokabular ist das von polygraph
(configs/start_vocabulary.json).
"""

from domains.base import DomainProfile, Qualifier

QUALIFIERS = (
    Qualifier("value", "value", "Wert"),
    Qualifier("condition", "condition", "Bedingung"),
    Qualifier("evidence_level", "evidence", "Evidenz"),
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

PROFILE = DomainProfile("generic", QUALIFIERS, ENTITY_TYPES, RELATION_TYPES)
