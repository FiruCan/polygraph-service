"""Fragen-Pakete und Antwort-Laeufe (pakete.py, /fragen) - nur temporaere Ordner."""

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as app_module
import pakete

PAKET = {"firma": "Coca-Cola", "ticker": "KO",
         "fragen": [{"id": "a", "stufe": "1", "frage": "Was stellt Coca-Cola her?"},
                    {"id": "b", "stufe": "2", "frage": "Mit wem konkurriert Coca-Cola?"}]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    fragen_dir, antworten_dir = tmp_path / "fragen", tmp_path / "antworten"
    eigene_dir = tmp_path / "eigene"
    fragen_dir.mkdir()
    (fragen_dir / "buffett_ko.json").write_text(json.dumps(PAKET), encoding="utf-8")
    (fragen_dir / "kaputt.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRAGEN_DIR", str(fragen_dir))
    monkeypatch.setattr(app_module, "ANTWORTEN_DIR", str(antworten_dir))
    monkeypatch.setattr(app_module, "EIGENE_DIR", str(eigene_dir))
    return TestClient(app_module.app)


def save(client, lauf, eintrag, **kopf):
    return client.post(f"/fragen/buffett_ko/antworten/{lauf}", json={"kopf": kopf, "eintrag": eintrag})


def test_lists_pakete_without_broken_files(client):
    pakete_ = client.get("/fragen").json()["pakete"]
    assert [p["name"] for p in pakete_] == ["buffett_ko"]
    assert pakete_[0]["anzahl"] == 2 and pakete_[0]["titel"] == "Coca-Cola" and pakete_[0]["letzter_lauf"] is None


def test_get_paket_and_unknown_is_404(client):
    assert client.get("/fragen/buffett_ko").json()["ticker"] == "KO"
    assert client.get("/fragen/gibt_es_nicht").status_code == 404


def test_save_replaces_entry_with_same_id_and_counts_verdicts(client):
    save(client, "2026-11-07-120000", {"id": "a", "urteil": "nein"}, modus="recherche",
         gestartet="2026-11-07T12:00:00+00:00")
    save(client, "2026-11-07-120000", {"id": "b", "urteil": "teilweise"})
    r = save(client, "2026-11-07-120000", {"id": "a", "urteil": "beantwortet"})
    assert r.status_code == 200
    assert r.json()["anzahl"] == 2 and r.json()["beantwortet"] == 1
    lauf = client.get("/fragen/buffett_ko/antworten/2026-11-07-120000").json()
    assert lauf["modus"] == "recherche" and lauf["lauf"] == "2026-11-07-120000"
    assert sorted(a["urteil"] for a in lauf["antworten"]) == ["beantwortet", "teilweise"]
    assert client.get("/fragen").json()["pakete"][0]["letzter_lauf"]["anzahl"] == 2


def test_laeufe_newest_first(client):
    save(client, "alt", {"id": "a"}, gestartet="2026-11-01T10:00:00+00:00")
    save(client, "neu", {"id": "a"}, gestartet="2026-11-07T10:00:00+00:00")
    assert [x["lauf"] for x in client.get("/fragen/buffett_ko/antworten").json()["laeufe"]] == ["neu", "alt"]


def test_rejects_path_names_and_entries_without_id(client):
    assert save(client, "x.json", {"id": "a"}).status_code == 400
    assert save(client, "lauf", {"urteil": "nein"}).status_code == 400
    assert client.get("/fragen/buffett_ko/antworten/..%2Fx").status_code == 404
    with pytest.raises(FileNotFoundError):
        pakete.load_paket(app_module.FRAGEN_DIR, "../buffett_ko")


def upload(client, name, paket):
    return client.post("/fragen", json={"name": name, "paket": paket})


def test_upload_plain_questions_gets_ids_and_is_listed_after_the_given_ones(client):
    r = upload(client, "meine_fragen", {"titel": "Meine", "fragen": ["Was macht Apple?", "  ", {"frage": "Wer fuehrt Apple?"}]})
    assert r.status_code == 200 and r.json()["anzahl"] == 2 and r.json()["eigen"] is True
    paket = client.get("/fragen/meine_fragen").json()
    assert [q["id"] for q in paket["fragen"]] == ["frage_1", "frage_3"] and paket["fragen"][1]["frage"] == "Wer fuehrt Apple?"
    listed = client.get("/fragen").json()["pakete"]
    assert [(p["name"], p["eigen"]) for p in listed] == [("buffett_ko", False), ("meine_fragen", True)]
    # gleicher Name ersetzt das eigene Paket
    upload(client, "meine_fragen", {"fragen": ["Nur noch eine?"]})
    assert client.get("/fragen").json()["pakete"][1]["anzahl"] == 1


def test_upload_rejects_given_names_bad_names_and_bad_content(client):
    assert upload(client, "buffett_ko", {"fragen": ["x?"]}).status_code == 409
    assert upload(client, "../x", {"fragen": ["x?"]}).status_code == 400
    assert upload(client, "leer", {"fragen": ["  "]}).status_code == 400
    assert upload(client, "ohne", {"titel": "x"}).status_code == 400
    assert upload(client, "doppelt", {"fragen": [{"id": "a", "frage": "1?"}, {"id": "a", "frage": "2?"}]}).status_code == 400


def test_delete_only_own_pakete_and_keeps_their_answers(client):
    upload(client, "meine", {"fragen": ["Was macht Apple?"]})
    client.post("/fragen/meine/antworten/lauf1", json={"kopf": {}, "eintrag": {"id": "frage_1"}})
    assert client.delete("/fragen/buffett_ko").status_code == 404
    assert client.delete("/fragen/meine").status_code == 200
    assert client.get("/fragen/meine").status_code == 404
    assert client.get("/fragen/meine/antworten/lauf1").status_code == 200


def test_metis_may_delete_across_ports(client):
    r = client.options("/fragen/meine", headers={"Origin": "http://localhost:8001",
                                                 "Access-Control-Request-Method": "DELETE"})
    assert r.status_code == 200 and "DELETE" in r.headers["access-control-allow-methods"]
