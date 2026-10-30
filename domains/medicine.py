"""
medicine.py
-----------
Profil Medizin. Die Angaben an den Kanten sind die, mit denen der Graph
schon immer gearbeitet hat (value, condition, evidence_level) - ein
bestehender Graph wechselt deshalb ohne Verhaltensaenderung auf "medicine".
Das Vokabular ist vorerst das allgemeine; Biolink-Kategorien als Wurzeltypen
der Typ-Hierarchie folgen.
"""

from domains import generic
from domains.base import DomainProfile

PROFILE = DomainProfile("medicine", generic.QUALIFIERS, generic.ENTITY_TYPES, generic.RELATION_TYPES,
                        example_text=generic.EXAMPLE_TEXT, example_output=generic.EXAMPLE_OUTPUT)
