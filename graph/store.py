"""
store.py
--------
Kapselt den eigentlichen Graph-Speicher (aktuell NetworkX). Absichtlich so
geschnitten, dass ein spaeterer Umstieg auf Neo4j nur diese eine Datei
betrifft, nicht den Rest des Service (app.py, normalize.py, ask.py bleiben
unveraendert).
"""

import json
import os
from collections import Counter

import networkx as nx


def hierarchy_path(graph_path: str) -> str:
    """
    Datei der Typ-Hierarchie neben dem Graphen: data/graph.gml ->
    data/graph.hierarchy.json, ein Backup graph.backup-<Zeit>.gml ->
    graph.backup-<Zeit>.hierarchy.json - so bleiben Paare zusammen.
    """
    return os.path.splitext(graph_path)[0] + ".hierarchy.json"


def _leads_back(parents: dict, start: str) -> bool:
    """True, wenn die Obertypen von 'start' wieder bei 'start' ankommen (Kreis)."""
    seen, current = set(), start
    while current in parents:
        current = parents[current]
        if current == start:
            return True
        if current in seen:  # Kreis weiter oben, nicht durch start
            return False
        seen.add(current)
    return False


def load_graph(path: str) -> "GraphStore":
    """Laedt einen Graphen aus einer .gml-Datei oder baut ihn aus einer Tripel-.json."""
    store = GraphStore()
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            for triple in json.load(f):
                store.add_triple(triple)
    else:
        store.load(path)
    return store


class GraphStore:
    def __init__(self):
        self.graph = nx.MultiDiGraph()
        # Typ-Hierarchie: Typ -> Obertyp ("disease" -> "condition"), siehe
        # set_type_parents(). Getrennt vom Graphen, damit Typen nicht als
        # Knoten in /graph, Antworten und Fragevorschlaegen auftauchen.
        self.type_parents = {}

    def add_triple(self, triple: dict):
        """
        Legt Subjekt- und Objekt-Knoten an (falls noch nicht vorhanden) und
        fuegt eine Kante mit allen Zusatzfeldern (relation, value, condition,
        evidence_level, confidence, origin, ...) als Properties hinzu.

        Ein optionales "source"-Feld im Tripel (z.B. die Artikel-URL) wird
        intern als Kanten-Attribut "origin" gespeichert, NICHT als "source":
        GML (unser Speicherformat, siehe save()/load()) behandelt "source"
        als reserviertes Schluesselwort fuer den Kanten-Startknoten und
        wirft ein gleichnamiges Attribut beim Schreiben stillschweigend weg.

        Existiert zwischen Subjekt und Objekt bereits eine Kante mit
        derselben Relation UND demselben "origin" (z.B. weil dieselbe Quelle
        zweimal importiert wurde), wird diese Kante aktualisiert statt eine
        zusaetzliche parallele Kante anzulegen. Behauptet eine ANDERE Quelle
        (oder keine) dieselbe Relation zwischen denselben Knoten, bleibt das
        eine eigene Kante - das ist keine Duplizierung, sondern zwei
        Belegstellen fuer dieselbe Aussage.
        """
        self._add_or_update_node(triple["subject"], triple.get("subject_type"))
        self._add_or_update_node(triple["object"], triple.get("object_type"))

        edge_props = {
            k: v
            for k, v in triple.items()
            if k not in ("subject", "subject_type", "object", "object_type", "source")
            and v is not None
        }
        if triple.get("source") is not None:
            edge_props["origin"] = triple["source"]

        existing_key = self._find_edge_key(
            triple["subject"], triple["object"], triple.get("relation"), triple.get("source")
        )
        if existing_key is not None:
            self.graph.edges[triple["subject"], triple["object"], existing_key].update(edge_props)
        else:
            self.graph.add_edge(triple["subject"], triple["object"], **edge_props)

    def _add_or_update_node(self, node: str, node_type):
        """
        Legt den Knoten an oder aktualisiert einen bestehenden - den Typ
        aber NUR, wenn node_type nicht None ist. Verhindert, dass ein
        bereits bekannter, echter Typ durch ein spaeteres Tripel ohne
        Typangabe stillschweigend mit None ueberschrieben wird.

        Ein unbekannter Typ wird gar nicht als Attribut gesetzt (statt
        type=None): write_gml kann None nicht schreiben - ein einziges
        Tripel ohne Typ liess sonst JEDES weitere save() scheitern, bis der
        Service neu startete. to_json() liefert fehlende Typen als None.
        """
        if not self.graph.has_node(node):
            self.graph.add_node(node)
        if node_type is not None:
            self.graph.nodes[node]["type"] = node_type

    def _find_edge_key(self, u: str, v: str, relation, source=None):
        """Key der Kante u->v mit gegebener Relation UND Quelle ("origin"), falls vorhanden, sonst None."""
        if not self.graph.has_edge(u, v):
            return None
        for key, data in self.graph[u][v].items():
            if data.get("relation") == relation and data.get("origin") == source:
                return key
        return None

    def remove_edges_by_source(self, source: str):
        """
        Entfernt alle Kanten mit diesem "origin"-Wert (fuer erneuten Import
        derselben Quelle: erst loeschen, dann frisch extrahierte Kanten
        einfuegen, statt veraltete Kanten aus einem frueheren Extraktions-
        Lauf stehen zu lassen). Knoten, die dadurch keine Kanten mehr haben,
        werden mit entfernt.
        """
        to_remove = [
            (u, v, k) for u, v, k, data in self.graph.edges(keys=True, data=True)
            if data.get("origin") == source
        ]
        self.graph.remove_edges_from(to_remove)

        isolated = [n for n in self.graph.nodes if self.graph.degree(n) == 0]
        self.graph.remove_nodes_from(isolated)

    def known_entities(self) -> list[str]:
        return list(self.graph.nodes)

    def known_relations(self) -> list[str]:
        return sorted({
            data["relation"]
            for _, _, data in self.graph.edges(data=True)
            if "relation" in data
        })

    def known_types(self) -> list[str]:
        return sorted({data["type"] for _, data in self.graph.nodes(data=True) if "type" in data})

    def vocabulary(self) -> dict:
        """
        Knotentypen und Relationen mit Haeufigkeit, haeufigste zuerst. Das
        Vokabular waechst aus den Artikeln, die importiert werden - es gibt
        keine fest eingestellte Domain. polygraph gibt die haeufigen Begriffe
        der Extraktion als bekanntes Vokabular mit (GET /vocabulary), die
        Prompts hier die haeufigsten Typen als Fachgebiet (topics()).
        Dazu die Typ-Hierarchie (type_parents), auch fuer Typen ohne Knoten.
        """
        types = Counter(data["type"] for _, data in self.graph.nodes(data=True) if data.get("type"))
        relations = Counter(data["relation"] for _, _, data in self.graph.edges(data=True)
                            if data.get("relation"))

        def listed(counts):
            return [{"name": name, "count": n}
                    for name, n in sorted(counts.items(), key=lambda i: (-i[1], i[0]))]

        return {"types": listed(types), "relations": listed(relations),
                "type_parents": dict(sorted(self.type_parents.items()))}

    def topics(self, extra_types=(), limit: int = 15) -> str:
        """
        Die haeufigsten Knotentypen als kurze Liste ("disease, drug, ...") -
        sagt den Prompts, worum es in diesem Graphen geht, z.B. um
        mehrdeutige Woerter richtig zu uebersetzen. extra_types (die Typen
        gerade importierter Tripel) zaehlen mit: ein junger Graph hat noch
        kaum eigene Typen. Leer, wenn es noch keine gibt.
        """
        counts = Counter(data["type"] for _, data in self.graph.nodes(data=True) if data.get("type"))
        counts.update(t for t in extra_types if isinstance(t, str) and t.strip())
        return ", ".join(name for name, _ in counts.most_common(limit))

    def rename_relation(self, old: str, new: str) -> int:
        """
        Benennt eine Relation auf allen Kanten um (Vokabular-Steward in
        polygraph: z.B. "lowers" -> "reduces"). Gibt die Anzahl geaenderter
        Kanten zurueck. relation_is_new wird mit entfernt - die Kante traegt
        danach eine bekannte Relation.
        """
        changed = 0
        for _, _, data in self.graph.edges(data=True):
            if data.get("relation") == old:
                data["relation"] = new
                data.pop("relation_is_new", None)
                changed += 1
        return changed

    def retype_nodes(self, old: str, new: str) -> int:
        """
        Setzt den Typ aller Knoten mit Typ 'old' auf 'new', gibt die Anzahl
        zurueck. Die Typ-Hierarchie zieht nicht von selbst mit - dafuer
        rename_type_in_hierarchy().
        """
        changed = 0
        for _, data in self.graph.nodes(data=True):
            if data.get("type") == old:
                data["type"] = new
                changed += 1
        return changed

    def set_type_parents(self, parents: dict) -> int:
        """
        Typ-Hierarchie: setzt pro Typ den Obertyp ("disease" -> "condition"),
        None entfernt ihn. Obertypen brauchen keine Knoten - die Wurzeln
        (polygraph configs/start_vocabulary.json) haben meist keine. Alles
        oder nichts: ein leerer Name, ein Typ als sein eigener Obertyp oder
        ein Kreis ("cell" -> "immune_cell" -> "cell") -> ValueError, nichts
        aendert sich. Gibt die Anzahl geaenderter Eintraege zurueck.
        """
        updated = dict(self.type_parents)
        for child, parent in parents.items():
            if not child.strip() or (parent is not None and not parent.strip()):
                raise ValueError("leerer Typname")
            if parent is None:
                updated.pop(child, None)
            else:
                updated[child] = parent
        # Ein neuer Kreis muesste durch einen der geaenderten Typen laufen
        for child in parents:
            if _leads_back(updated, child):
                raise ValueError(f"Kreis in der Typ-Hierarchie ueber '{child}'")
        changed = sum(1 for child in parents if self.type_parents.get(child) != updated.get(child))
        self.type_parents = updated
        return changed

    def rename_type_in_hierarchy(self, old: str, new: str) -> bool:
        """
        Zieht die Typ-Hierarchie bei einer Umbenennung mit (POST
        /vocabulary/rename): Untertypen von 'old' haengen danach an 'new'.
        Gibt es 'new' schon (Steward: "zuordnen"), behaelt 'new' seinen
        Obertyp; hat es keinen, uebernimmt es den von 'old'. Ein Obertyp,
        der einen Kreis ergaebe (z.B. 'old' war Obertyp von 'new'), wird
        uebersprungen. Gibt zurueck, ob sich etwas geaendert hat.
        """
        if old == new:
            return False
        before = dict(self.type_parents)
        parents = self.type_parents
        old_parent, new_parent = parents.pop(old, None), parents.pop(new, None)
        for child, parent in parents.items():
            if parent == old:
                parents[child] = new
        for candidate in (new_parent, old_parent):
            if candidate is None:
                continue
            parents[new] = new if candidate == old else candidate
            if _leads_back(parents, new):
                del parents[new]
            else:
                break
        return parents != before

    def rewrite_edge_field(self, field: str, old: str, new: str) -> int:
        """Setzt das Feld auf allen Kanten mit Wert 'old' auf 'new' (z.B. "Metaanalyse" -> "meta-analysis")."""
        changed = 0
        for _, _, data in self.graph.edges(data=True):
            if data.get(field) == old:
                data[field] = new
                changed += 1
        return changed

    def merge_nodes(self, keep: str, remove: str) -> dict:
        """
        Fuehrt 'remove' in 'keep' zusammen (Duplikat-Aufraeumer, nach Freigabe):
        alle Kanten von/zu 'remove' haengen danach an 'keep', 'remove' wird
        geloescht. Den Typ von 'remove' erbt 'keep' nur, wenn es selbst keinen hat.

        - Kanten zwischen den beiden ("MS --abbreviation_of--> multiple
          Sklerose") wuerden zur Schleife keep -> keep und fallen weg.
        - Gibt es an 'keep' schon dieselbe Kante (Relation + Quelle), wird
          nicht verdoppelt, sondern zusammengelegt - wie bei add_triple();
          fehlende Felder der bestehenden Kante werden ergaenzt.
        -> {"moved", "collapsed", "dropped_self_loops"}. KeyError, wenn ein
        Knoten fehlt; ValueError bei keep == remove.
        """
        if keep == remove:
            raise ValueError("keep und remove sind derselbe Knoten")
        for node in (keep, remove):
            if not self.graph.has_node(node):
                raise KeyError(node)

        edges = {(u, v, k): data for u, v, k, data in self.graph.out_edges(remove, keys=True, data=True)}
        edges.update({(u, v, k): data for u, v, k, data in self.graph.in_edges(remove, keys=True, data=True)})

        stats = {"moved": 0, "collapsed": 0, "dropped_self_loops": 0}
        for (u, v, _), data in edges.items():
            u, v = (keep if u == remove else u), (keep if v == remove else v)
            if u == v:
                stats["dropped_self_loops"] += 1
                continue
            existing = self._find_edge_key(u, v, data.get("relation"), data.get("origin"))
            if existing is None:
                self.graph.add_edge(u, v, **data)
                stats["moved"] += 1
            else:
                target = self.graph.edges[u, v, existing]
                for key, value in data.items():
                    target.setdefault(key, value)
                stats["collapsed"] += 1

        removed_type = self.graph.nodes[remove].get("type")
        if removed_type is not None and self.graph.nodes[keep].get("type") is None:
            self.graph.nodes[keep]["type"] = removed_type
        self.graph.remove_node(remove)
        return stats

    def rename_node(self, old: str, new: str) -> dict:
        """
        Benennt einen Knoten um (Umstellung auf englische Namen,
        translate_graph.py). Gibt es 'new' schon, wird 'old' dorthin
        zusammengefuehrt (merge_nodes) statt einen zweiten Knoten anzulegen.
        -> {"merged": bool, ...Zaehler von merge_nodes}. KeyError, wenn 'old'
        fehlt; ValueError bei old == new.
        """
        if old == new:
            raise ValueError("alter und neuer Name sind gleich")
        if not self.graph.has_node(old):
            raise KeyError(old)
        if self.graph.has_node(new):
            return {"merged": True, **self.merge_nodes(new, old)}
        nx.relabel_nodes(self.graph, {old: new}, copy=False)
        return {"merged": False}

    def edges_by_relation(self, node: str, relation: str, direction: str = "out"):
        """Alle Kanten eines bestimmten Relationstyps an einem Knoten."""
        edge_view = self.graph.out_edges if direction == "out" else self.graph.in_edges
        return [
            (u, v, data)
            for u, v, data in edge_view(node, data=True)
            if data.get("relation") == relation
        ]

    def shortest_path(self, source: str, target: str):
        return nx.shortest_path(self.graph, source, target)

    def neighbors(self, node: str):
        return list(self.graph.neighbors(node))

    def save(self, path: str):
        """
        Schreibt in eine temporaere Datei im selben Verzeichnis und benennt
        sie erst danach atomar auf den Zielpfad um (os.replace). Schreiben
        direkt auf den Zielpfad wuerde bei einem Absturz/Fehler mitten im
        Schreiben (z.B. ein nicht serialisierbarer Attributwert) eine
        abgeschnittene, kaputte Datei zuruecklassen und den vorherigen,
        gueltigen Stand zerstoeren - das ist real passiert, nicht nur
        theoretisch.

        Die Typ-Hierarchie kommt genauso daneben (hierarchy_path) - aber erst,
        wenn es eine gibt, damit ein Graph ohne Hierarchie keine leere Datei
        bekommt.
        """
        tmp_path = f"{path}.tmp"
        nx.write_gml(self.graph, tmp_path)
        os.replace(tmp_path, path)

        hierarchy = hierarchy_path(path)
        if self.type_parents or os.path.exists(hierarchy):
            with open(f"{hierarchy}.tmp", "w", encoding="utf-8") as f:
                json.dump(dict(sorted(self.type_parents.items())), f, ensure_ascii=False, indent=2)
            os.replace(f"{hierarchy}.tmp", hierarchy)

    def load(self, path: str):
        self.graph = nx.read_gml(path)
        hierarchy = hierarchy_path(path)
        self.type_parents = {}
        if os.path.exists(hierarchy):
            with open(hierarchy, "r", encoding="utf-8") as f:
                self.type_parents = json.load(f)

    def to_json(self) -> dict:
        """Serialisiert den Graphen fuer die API (GET /graph, Teilgraph in POST /ask)."""
        return {
            "nodes": [
                {"id": str(node), "type": data.get("type")}
                for node, data in self.graph.nodes(data=True)
            ],
            "edges": [
                {
                    "source": str(u),
                    "target": str(v),
                    "relation": data.get("relation"),
                    "value": data.get("value"),
                    "condition": data.get("condition"),
                    "evidence_level": data.get("evidence_level"),
                    "confidence": data.get("confidence"),
                    "origin": data.get("origin"),
                }
                for u, v, data in self.graph.edges(data=True)
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "GraphStore":
        """Baut einen GraphStore aus dem von to_json() erzeugten Format (fuer Teilgraphen)."""
        store = cls()
        for node in data["nodes"]:
            store.graph.add_node(node["id"], type=node.get("type"))
        for edge in data["edges"]:
            props = {k: v for k, v in edge.items() if k not in ("source", "target") and v is not None}
            store.graph.add_edge(edge["source"], edge["target"], **props)
        return store
