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
    fragen_dir.mkdir()
    (fragen_dir / "buffett_ko.json").write_text(json.dumps(PAKET), encoding="utf-8")
    (fragen_dir / "kaputt.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRAGEN_DIR", str(fragen_dir))
    monkeypatch.setattr(app_module, "ANTWORTEN_DIR", str(antworten_dir))
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
