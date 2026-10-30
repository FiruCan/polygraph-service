"""
domains
-------
Domaenen-Profile (domains/base.py): pro Instanz ein Fachgebiet,
"medicine" oder "finance" ("generic" ohne Fachgebiet). Der Name steht als Graph-Attribut in der graph.gml selbst
(graph.graph["profile"]) - so gehen Backups und Umstellungen nie ohne ihr
Profil, und jeder Teil des Kerns, der den Graphen hat, kennt auch dessen
Profil (profile_of).

Festgelegt wird es einmal (assign_profile, beim Start aus POLYGRAPH_DOMAIN)
und gilt danach fest: ein anderes Profil fuer denselben Graphen ist ein
Fehler, kein Wechsel.
"""

from domains import finance, generic, medicine
from domains.base import DomainProfile, Qualifier

PROFILES = {p.name: p for p in (generic.PROFILE, medicine.PROFILE, finance.PROFILE)}
DEFAULT_PROFILE = generic.PROFILE.name


def get_profile(name: str) -> DomainProfile:
    if name not in PROFILES:
        raise ValueError(f"Unbekanntes Profil '{name}' - bekannt: {', '.join(sorted(PROFILES))}")
    return PROFILES[name]


def profile_of(graph) -> DomainProfile:
    """Profil eines NetworkX-Graphen; ohne zugewiesenes Profil das allgemeine."""
    return get_profile(graph.graph.get("profile", DEFAULT_PROFILE))


def assign_profile(graph, requested: str = None) -> bool:
    """
    Legt das Profil des Graphen fest. True, wenn sich graph.graph dadurch
    geaendert hat (dann speichern).
    - Hat der Graph schon eins, muss requested (falls angegeben) dazu passen,
      sonst ValueError.
    - requested ohne gespeichertes Profil: wird zugewiesen (Migration eines
      alten Graphen, oder eine neue Instanz).
    - Weder noch: eine leere, neue Instanz bekommt das allgemeine Profil fest;
      ein alter Graph mit Inhalt bleibt ohne, damit er spaeter noch bewusst
      einem Fachgebiet zugeordnet werden kann (profile_of liefert solange
      das allgemeine).
    """
    stored = graph.graph.get("profile")
    if requested:
        get_profile(requested)
    if stored:
        get_profile(stored)
        if requested and requested != stored:
            raise ValueError(f"Der Graph hat das Profil '{stored}', verlangt ist '{requested}' - "
                             "ein Profil wird nicht gewechselt, dafuer eine eigene Instanz starten")
        return False
    if requested:
        graph.graph["profile"] = requested
        return True
    if graph.number_of_nodes() == 0:
        graph.graph["profile"] = DEFAULT_PROFILE
        return True
    return False


__all__ = ["DomainProfile", "Qualifier", "PROFILES", "DEFAULT_PROFILE",
           "get_profile", "profile_of", "assign_profile"]
