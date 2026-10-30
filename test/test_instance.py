"""
Tests fuer den Start einer Instanz (app.open_instance): Datenordner pro
Fachgebiet, Sperre gegen zwei Instanzen auf demselben Ordner, Abbruch bei
fehlendem Fachgebiet oder altem data/graph.gml. Alles in tmp_path - der
echte Datenordner wird nie beruehrt.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as app_module
import graph.localize as label_cache
from domains import assign_profile, profile_of
from graph.store import GraphStore


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(app_module, "store", GraphStore())
    monkeypatch.setattr(app_module, "DATA_PATH", None)
    monkeypatch.setattr(app_module, "_instance_lock", None)
    monkeypatch.setattr(label_cache, "CACHE_DIR", label_cache.CACHE_DIR)
    yield tmp_path
    if app_module._instance_lock:
        app_module._instance_lock.close()


def write_graph(path, profile=None):
    store = GraphStore()
    if profile:
        assign_profile(store.graph, profile)
    store.add_triple({"subject": "a", "relation": "r", "object": "b"})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    store.save(str(path))


def test_new_instance_gets_its_own_folder(root):
    app_module.open_instance("medicine")
    assert app_module.DATA_PATH == str(root / "medicine" / "graph.gml")
    assert label_cache.CACHE_DIR == str(root / "medicine" / "labels")
    assert profile_of(app_module.store.graph).name == "medicine"
    assert not os.path.exists(app_module.DATA_PATH)  # erst beim ersten Import


def test_existing_graph_is_loaded_and_gets_its_profile(root):
    write_graph(root / "medicine" / "graph.gml")
    app_module.open_instance("medicine")
    assert app_module.store.graph.number_of_edges() == 1
    reloaded = GraphStore()
    reloaded.load(str(root / "medicine" / "graph.gml"))
    assert reloaded.graph.graph["profile"] == "medicine"


def test_missing_or_unknown_domain_stops_the_start(root):
    with pytest.raises(RuntimeError, match="POLYGRAPH_DOMAIN fehlt"):
        app_module.open_instance(None)
    with pytest.raises(ValueError, match="Unbekanntes Profil"):
        app_module.open_instance("astrology")
    assert os.listdir(root) == []


def test_old_graph_in_data_root_is_not_moved(root):
    write_graph(root / "graph.gml")
    with pytest.raises(RuntimeError, match="verschieben"):
        app_module.open_instance("medicine")
    assert os.path.exists(root / "graph.gml")
    assert not os.path.exists(root / "medicine")


def test_folder_of_another_domain_is_refused(root):
    write_graph(root / "medicine" / "graph.gml", profile="generic")
    with pytest.raises(ValueError, match="nicht gewechselt"):
        app_module.open_instance("medicine")


def test_second_instance_on_same_folder_is_refused(root):
    app_module.open_instance("medicine")
    with pytest.raises(RuntimeError, match="schon von einem anderen"):
        app_module.lock_data_dir(str(root / "medicine"))


def test_other_folder_can_run_in_parallel(root):
    app_module.open_instance("medicine")
    os.makedirs(root / "generic")
    other = app_module.lock_data_dir(str(root / "generic"))
    other.close()


def test_lock_ends_with_its_holder(root):
    first = app_module.lock_data_dir(str(root))
    first.close()
    app_module.lock_data_dir(str(root)).close()


def test_server_start_opens_the_instance(root, monkeypatch):
    write_graph(root / "medicine" / "graph.gml")
    monkeypatch.setenv("POLYGRAPH_DOMAIN", "medicine")
    with TestClient(app_module.app) as client:
        assert client.get("/health").json() == {"status": "ok", "nodes": 2, "edges": 1}
        assert client.get("/profile").json()["fixed"] is True
