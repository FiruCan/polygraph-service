"""
store.py
--------
Kapselt den eigentlichen Graph-Speicher (aktuell NetworkX). Absichtlich so
geschnitten, dass ein spaeterer Umstieg auf Neo4j nur diese eine Datei
betrifft, nicht den Rest des Service (app.py, normalize.py, ask.py bleiben
unveraendert).
"""

import json

import networkx as nx


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
        self.graph.add_node(triple["subject"], type=triple.get("subject_type"))
        self.graph.add_node(triple["object"], type=triple.get("object_type"))

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
        nx.write_gml(self.graph, path)

    def load(self, path: str):
        self.graph = nx.read_gml(path)

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
