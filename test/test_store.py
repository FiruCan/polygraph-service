"""
Unit-Tests fuer graph/store.py (GraphStore). Kein Ollama noetig.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graph.store import GraphStore, load_graph


def triple(subject="Krafttraining", relation="reduces_risk_of", obj="Krebs", **extra):
    t = {"subject": subject, "subject_type": "lifestyle_factor", "relation": relation,
         "object": obj, "object_type": "disease"}
    t.update(extra)
    return t


def test_add_triple_creates_nodes_and_edge_with_props():
    store = GraphStore()
    store.add_triple(triple(value="20 Prozent", condition=None, confidence=0.9))
    g = store.graph
    assert g.nodes["Krafttraining"]["type"] == "lifestyle_factor"
    data = g.get_edge_data("Krafttraining", "Krebs")[0]
    assert data["relation"] == "reduces_risk_of"
    assert data["value"] == "20 Prozent"
    assert "condition" not in data  # None-Werte werden nicht gespeichert


def test_source_is_stored_as_origin():
    # "source" ist in GML reserviert und wuerde beim Speichern verschwinden
    store = GraphStore()
    store.add_triple(triple(source="https://example.org/a"))
    data = store.graph.get_edge_data("Krafttraining", "Krebs")[0]
    assert data["origin"] == "https://example.org/a"
    assert "source" not in data


def test_same_relation_same_source_updates_instead_of_duplicating():
    store = GraphStore()
    store.add_triple(triple(source="A", confidence=0.5))
    store.add_triple(triple(source="A", confidence=0.9))
    edges = store.graph.get_edge_data("Krafttraining", "Krebs")
    assert len(edges) == 1
    assert edges[0]["confidence"] == 0.9


def test_same_relation_other_source_is_separate_edge():
    store = GraphStore()
    store.add_triple(triple(source="A"))
    store.add_triple(triple(source="B"))
    assert len(store.graph.get_edge_data("Krafttraining", "Krebs")) == 2


def test_vocabulary_counts_types_and_relations_most_frequent_first():
    store = GraphStore()
    store.add_triple(triple())
    store.add_triple(triple(subject="Rauchen", relation="increases_risk_of", subject_type="risk_factor"))
    store.add_triple(triple(obj="Diabetes", relation="increases_risk_of"))
    vocab = store.vocabulary()
    assert vocab["types"] == [{"name": "disease", "count": 2}, {"name": "lifestyle_factor", "count": 1},
                              {"name": "risk_factor", "count": 1}]
    assert vocab["relations"] == [{"name": "increases_risk_of", "count": 2},
                                  {"name": "reduces_risk_of", "count": 1}]


def test_topics_are_most_frequent_types_including_new_ones():
    store = GraphStore()
    assert store.topics() == ""
    store.add_triple(triple())
    store.add_triple(triple(obj="Diabetes"))
    assert store.topics() == "disease, lifestyle_factor"
    # junger Graph: die Typen der gerade importierten Tripel zaehlen mit
    assert store.topics(["company", "company", "company", None, " "]) == "company, disease, lifestyle_factor"
    assert store.topics(limit=1) == "disease"


def test_node_type_not_overwritten_with_none():
    store = GraphStore()
    store.add_triple(triple())
    store.add_triple({"subject": "Krafttraining", "relation": "supports", "object": "Muskelaufbau"})
    assert store.graph.nodes["Krafttraining"]["type"] == "lifestyle_factor"


def test_remove_edges_by_source_removes_only_that_source_and_isolated_nodes():
    store = GraphStore()
    store.add_triple(triple(source="A"))
    store.add_triple(triple(subject="Rauchen", obj="Krebs", relation="increases_risk_of", source="B"))
    store.remove_edges_by_source("A")
    assert not store.graph.has_node("Krafttraining")  # isoliert -> entfernt
    assert store.graph.has_edge("Rauchen", "Krebs")


def test_known_entities_and_relations():
    store = GraphStore()
    store.add_triple(triple())
    store.add_triple(triple(subject="Rauchen", relation="increases_risk_of"))
    assert set(store.known_entities()) == {"Krafttraining", "Krebs", "Rauchen"}
    assert store.known_relations() == ["increases_risk_of", "reduces_risk_of"]


def test_known_types_skips_nodes_without_type():
    store = GraphStore()
    store.add_triple(triple())
    store.add_triple({"subject": "a", "relation": "r", "object": "b"})
    assert store.known_types() == ["disease", "lifestyle_factor"]


def test_edges_by_relation_and_neighbors():
    store = GraphStore()
    store.add_triple(triple())
    store.add_triple(triple(obj="Diabetes"))
    store.add_triple(triple(relation="supports", obj="Muskelaufbau"))
    out = store.edges_by_relation("Krafttraining", "reduces_risk_of")
    assert {v for _, v, _ in out} == {"Krebs", "Diabetes"}
    incoming = store.edges_by_relation("Krebs", "reduces_risk_of", direction="in")
    assert [u for u, _, _ in incoming] == ["Krafttraining"]
    assert set(store.neighbors("Krafttraining")) == {"Krebs", "Diabetes", "Muskelaufbau"}


def test_save_works_with_untyped_nodes(tmp_path):
    # Regression: type=None liess write_gml scheitern - und danach jedes save()
    store = GraphStore()
    store.add_triple({"subject": "A", "relation": "r", "object": "B"})
    path = str(tmp_path / "graph.gml")
    store.save(path)
    loaded = GraphStore()
    loaded.load(path)
    assert loaded.graph.has_edge("A", "B")
    assert loaded.to_json()["nodes"][0]["type"] is None


def test_save_load_roundtrip_keeps_origin_and_umlauts(tmp_path):
    store = GraphStore()
    store.add_triple(triple(obj="Entzündungen", source="https://example.org/ü", confidence=0.8))
    path = str(tmp_path / "graph.gml")
    store.save(path)
    assert not os.path.exists(path + ".tmp")

    loaded = GraphStore()
    loaded.load(path)
    data = loaded.graph.get_edge_data("Krafttraining", "Entzündungen")[0]
    assert data["origin"] == "https://example.org/ü"
    assert data["confidence"] == 0.8


def test_to_json_from_json_roundtrip():
    store = GraphStore()
    store.add_triple(triple(source="A", value="20 Prozent"))
    data = store.to_json()
    assert data["edges"][0]["origin"] == "A"
    rebuilt = GraphStore.from_json(data)
    assert rebuilt.to_json() == data


def test_load_graph_from_triples_json(tmp_path):
    import json
    path = tmp_path / "triples.json"
    path.write_text(json.dumps([triple()]), encoding="utf-8")
    store = load_graph(str(path))
    assert store.graph.has_edge("Krafttraining", "Krebs")


def test_rename_relation_changes_all_edges_and_clears_is_new():
    store = GraphStore()
    store.add_triple(triple(relation="lowers", relation_is_new=True))
    store.add_triple(triple(subject="Rauchen", relation="lowers"))
    store.add_triple(triple(subject="Sport", relation="supports"))
    assert store.rename_relation("lowers", "reduces") == 2
    assert store.known_relations() == ["reduces", "supports"]
    data = store.graph.get_edge_data("Krafttraining", "Krebs")[0]
    assert "relation_is_new" not in data


def test_retype_nodes():
    store = GraphStore()
    store.add_triple(triple())  # object_type "disease"
    store.add_triple(triple(obj="Demenz"))
    assert store.retype_nodes("disease", "condition") == 2
    assert store.graph.nodes["Krebs"]["type"] == "condition"
    assert store.retype_nodes("gibt_es_nicht", "x") == 0


# --- Typ-Hierarchie -----------------------------------------------------------

def test_set_type_parents_sets_removes_and_counts():
    store = GraphStore()
    assert store.set_type_parents({"disease": "condition", "immune_cell": "cell", "cell": "structure"}) == 3
    assert store.set_type_parents({"disease": "condition"}) == 0  # unveraendert
    assert store.set_type_parents({"immune_cell": None, "gibt_es_nicht": None}) == 1
    assert store.type_parents == {"disease": "condition", "cell": "structure"}


def test_set_type_parents_rejects_cycles_and_changes_nothing():
    store = GraphStore()
    store.set_type_parents({"immune_cell": "cell", "cell": "structure"})
    for bad in ({"structure": "immune_cell"}, {"cell": "cell"}, {"disease": "condition", "": "x"},
                {"monocytes": " "}):
        try:
            store.set_type_parents(bad)
            assert False, f"kein ValueError fuer {bad}"
        except ValueError:
            pass
    assert store.type_parents == {"immune_cell": "cell", "cell": "structure"}


def test_hierarchy_saved_next_to_graph_and_loaded(tmp_path):
    path = str(tmp_path / "graph.gml")
    store = GraphStore()
    store.add_triple(triple())
    store.save(path)
    assert not os.path.exists(tmp_path / "graph.hierarchy.json")  # keine Hierarchie, keine Datei

    store.set_type_parents({"disease": "condition", "Typ mit Ümlaut": "concept"})
    store.save(path)
    loaded = GraphStore()
    loaded.load(path)
    assert loaded.type_parents == {"disease": "condition", "Typ mit Ümlaut": "concept"}

    store.set_type_parents({"disease": None, "Typ mit Ümlaut": None})
    store.save(path)  # leer, aber die Datei gab es - wird geleert, nicht stehen gelassen
    loaded.load(path)
    assert loaded.type_parents == {}


def test_vocabulary_includes_hierarchy_without_nodes():
    store = GraphStore()
    store.add_triple(triple())
    store.set_type_parents({"disease": "condition", "condition": "state"})  # "condition" hat keine Knoten
    assert store.vocabulary()["type_parents"] == {"condition": "state", "disease": "condition"}


def test_rename_type_in_hierarchy_moves_type_and_children():
    store = GraphStore()
    store.set_type_parents({"cell_type": "structure", "immune_cell": "cell_type"})
    assert store.rename_type_in_hierarchy("cell_type", "cell") is True
    assert store.type_parents == {"cell": "structure", "immune_cell": "cell"}
    assert store.rename_type_in_hierarchy("gibt_es_nicht", "x") is False


def test_rename_type_onto_existing_keeps_its_parent():
    # Steward "zuordnen": "cells" -> "cell", beide schon eingeordnet
    store = GraphStore()
    store.set_type_parents({"cell": "structure", "cells": "concept", "T-cells": "cells"})
    store.rename_type_in_hierarchy("cells", "cell")
    assert store.type_parents == {"cell": "structure", "T-cells": "cell"}


def test_rename_type_onto_own_parent_or_child_makes_no_cycle():
    # 'old' ist Untertyp von 'new': kein "cell" -> "cell"
    store = GraphStore()
    store.set_type_parents({"cells": "cell"})
    store.rename_type_in_hierarchy("cells", "cell")
    assert store.type_parents == {}

    # 'old' ist Obertyp von 'new' (ueber einen Zwischentyp): 'new' nimmt den Obertyp von 'old'
    store.set_type_parents({"cell": "structure", "immune_cell": "cell", "monocytes": "immune_cell"})
    store.rename_type_in_hierarchy("cell", "monocytes")
    assert store.type_parents == {"monocytes": "structure", "immune_cell": "monocytes"}


def test_rename_node_keeps_edges_and_type():
    store = GraphStore()
    store.add_triple(triple())
    assert store.rename_node("Krebs", "cancer") == {"merged": False}
    assert store.graph.nodes["cancer"]["type"] == "disease"
    assert store.graph.has_edge("Krafttraining", "cancer") and "Krebs" not in store.graph


def test_rename_node_onto_existing_merges():
    store = GraphStore()
    store.add_triple(triple(obj="cancer"))
    store.add_triple(triple(obj="Krebs"))
    stats = store.rename_node("Krebs", "cancer")
    assert stats["merged"] and stats["collapsed"] == 1
    assert store.graph.number_of_edges() == 1


def test_rename_node_errors():
    import pytest
    store = GraphStore()
    store.add_triple(triple())
    with pytest.raises(KeyError):
        store.rename_node("gibtsnicht", "x")
    with pytest.raises(ValueError):
        store.rename_node("Krebs", "Krebs")


def test_rewrite_edge_field():
    store = GraphStore()
    store.add_triple(triple(evidence_level="Metaanalyse"))
    store.add_triple(triple(obj="Diabetes", evidence_level="RCT"))
    assert store.rewrite_edge_field("evidence_level", "Metaanalyse", "meta-analysis") == 1
    assert store.graph.get_edge_data("Krafttraining", "Krebs")[0]["evidence_level"] == "meta-analysis"
