"""
pakete.py
---------
Fragen-Pakete und ihre Antworten. Ein Paket ist eine JSON-Datei mit Fragen
zu einem Thema (question_packages/<fachgebiet>/<name>.json, z.B. die
Buffett-Fragen zu Coca-Cola), die Argos nacheinander recherchiert. Nach jeder Frage schickt
Argos die Antwort hierher; sie landet im Datenordner der Instanz
(data/<fachgebiet>/antworten/<name>/<lauf>.json), ein Lauf pro Paket-Start.
So bleibt ein frueherer Lauf erhalten und laesst sich mit einem spaeteren
vergleichen.

Vorgegebene Pakete liegen im Repo (question_packages/<fachgebiet>/), eigene,
in Metis hochgeladene im Datenordner (data/<fachgebiet>/question_packages/),
die Antworten auch dort (sie entstehen aus dem Graphen und gehoeren zu
ihm). Ein eigenes Paket darf kein vorgegebenes verdecken.
"""

import json
import os
import re
from datetime import datetime, timezone

# Paket- und Laufnamen werden zu Dateinamen - nur Buchstaben, Ziffern, _ und -
NAME = re.compile(r"^[\w-]{1,120}$")
URTEILE = ("beantwortet", "teilweise", "nein")


def valid_name(name: str) -> bool:
    return bool(NAME.match(name or ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data) -> None:
    """Erst in eine Nebendatei, dann umbenennen - ein Absturz hinterlaesst nie eine halbe Datei."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _dirs(fragen_dir: str, eigene_dir: str = None) -> list:
    return [(d, d == eigene_dir) for d in (fragen_dir, eigene_dir) if d]


def load_paket(fragen_dir: str, name: str, eigene_dir: str = None) -> dict:
    """-> Inhalt von <name>.json (vorgegeben vor eigen); FileNotFoundError, wenn es das Paket nicht gibt."""
    if not valid_name(name):
        raise FileNotFoundError(name)
    for directory, _ in _dirs(fragen_dir, eigene_dir):
        path = os.path.join(directory, name + ".json")
        if os.path.exists(path):
            return _read(path)
    raise FileNotFoundError(name)


def normalize(data) -> dict:
    """
    Ein hochgeladenes Paket pruefen und vereinheitlichen. Fragen duerfen
    blosse Texte sein ({"fragen": ["Was ...?", ...]}) oder Objekte mit
    frage, stufe und id; fehlt die id, wird sie durchgezaehlt (frage_1, ...).
    Weitere Felder (titel, firma, ticker, luecken, ...) bleiben, wie sie sind.
    -> das Paket; ValueError mit dem Grund, wenn es nicht taugt
    """
    if not isinstance(data, dict) or not isinstance(data.get("fragen"), list):
        raise ValueError('Das Paket braucht eine Liste "fragen"')
    fragen, ids = [], set()
    for i, q in enumerate(data["fragen"]):
        if isinstance(q, str):
            q = {"frage": q}
        if not isinstance(q, dict) or not isinstance(q.get("frage"), str):
            raise ValueError(f'Frage {i + 1}: braucht einen Text in "frage"')
        if not q["frage"].strip():
            continue
        q = {**q, "frage": q["frage"].strip(), "id": str(q.get("id") or f"frage_{i + 1}")}
        if not valid_name(q["id"]) or q["id"] in ids:
            raise ValueError(f"Frage {i + 1}: id '{q['id']}' ist doppelt oder enthaelt andere Zeichen "
                             "als Buchstaben, Ziffern, _ und -")
        ids.add(q["id"])
        fragen.append(q)
    if not fragen:
        raise ValueError("Das Paket hat keine Fragen")
    return {**data, "fragen": fragen}


def save_paket(fragen_dir: str, eigene_dir: str, name: str, data) -> dict:
    """
    Ein eigenes Paket speichern; ein gleichnamiges eigenes wird ersetzt
    (seine Antwort-Laeufe bleiben). -> Kurzfassung wie in list_pakete
    ValueError bei falschem Namen oder Inhalt, FileExistsError, wenn es ein
    vorgegebenes Paket dieses Namens gibt.
    """
    if not valid_name(name):
        raise ValueError("Paketname: nur Buchstaben, Ziffern, _ und -")
    if os.path.exists(os.path.join(fragen_dir, name + ".json")):
        raise FileExistsError(name)
    data = normalize(data)
    data["hochgeladen"] = _now()
    _write(os.path.join(eigene_dir, name + ".json"), data)
    return _paket_summary(name, data, True, [])


def delete_paket(eigene_dir: str, name: str) -> None:
    """Ein eigenes Paket loeschen; seine Antwort-Laeufe bleiben. FileNotFoundError, wenn es keins ist."""
    if not valid_name(name):
        raise FileNotFoundError(name)
    os.remove(os.path.join(eigene_dir, name + ".json"))


def _summary(lauf: dict) -> dict:
    antworten = lauf.get("antworten") or []
    zaehler = {u: sum(1 for a in antworten if a.get("urteil") == u) for u in URTEILE}
    return {k: lauf.get(k) for k in ("lauf", "modus", "auto_freigabe", "gestartet", "aktualisiert")} \
        | {"anzahl": len(antworten), **zaehler}


def list_laeufe(antworten_dir: str, name: str) -> list:
    """Die Antwort-Laeufe eines Pakets, neueste zuerst - kurz, ohne Antworten."""
    directory = os.path.join(antworten_dir, name)
    if not valid_name(name) or not os.path.isdir(directory):
        return []
    laeufe = []
    for file in os.listdir(directory):
        if file.endswith(".json"):
            try:
                laeufe.append(_summary(_read(os.path.join(directory, file))))
            except (OSError, ValueError):
                continue  # kaputte Datei nicht die ganze Liste kosten lassen
    laeufe.sort(key=lambda x: x.get("gestartet") or "", reverse=True)
    return laeufe


def _paket_summary(name: str, data: dict, eigen: bool, laeufe: list) -> dict:
    return {"name": name, "titel": data.get("titel") or data.get("firma") or name,
            "firma": data.get("firma"), "ticker": data.get("ticker"),
            "anzahl": len(data.get("fragen") or []), "eigen": eigen,
            "letzter_lauf": laeufe[0] if laeufe else None}


def list_pakete(fragen_dir: str, antworten_dir: str, eigene_dir: str = None) -> list:
    """Alle Pakete des Fachgebiets - erst die vorgegebenen, dann die eigenen -
    mit Zahl der Fragen und dem letzten Antwort-Lauf."""
    pakete, seen = [], set()
    for directory, eigen in _dirs(fragen_dir, eigene_dir):
        if not os.path.isdir(directory):
            continue
        for file in sorted(os.listdir(directory)):
            name, ext = os.path.splitext(file)
            if ext != ".json" or not valid_name(name) or name in seen:
                continue
            try:
                data = _read(os.path.join(directory, file))
            except (OSError, ValueError):
                continue
            seen.add(name)
            pakete.append(_paket_summary(name, data, eigen, list_laeufe(antworten_dir, name)))
    return pakete


def load_lauf(antworten_dir: str, name: str, lauf: str) -> dict:
    if not (valid_name(name) and valid_name(lauf)):
        raise FileNotFoundError(lauf)
    return _read(os.path.join(antworten_dir, name, lauf + ".json"))


def save_antwort(antworten_dir: str, name: str, lauf: str, kopf: dict, eintrag: dict) -> dict:
    """
    Eine Antwort in den Lauf schreiben. kopf (Modus, Start, ...) gilt fuer
    den ganzen Lauf; eintrag ersetzt einen frueheren mit derselben id - eine
    Frage, die Argos nach einem Abbruch neu stellt, steht so nur einmal da.
    -> Kurzfassung des Laufs
    """
    if not (valid_name(name) and valid_name(lauf)):
        raise ValueError("Paket- und Laufname: nur Buchstaben, Ziffern, _ und -")
    if not eintrag.get("id"):
        raise ValueError("Der Eintrag braucht eine id")
    path = os.path.join(antworten_dir, name, lauf + ".json")
    try:
        data = _read(path)
    except FileNotFoundError:
        data = {"name": name, "lauf": lauf, "antworten": []}
    data.update({k: v for k, v in kopf.items() if k not in ("name", "lauf", "antworten")})
    data["antworten"] = [a for a in data["antworten"] if a.get("id") != eintrag["id"]] + [eintrag]
    data["aktualisiert"] = _now()
    _write(path, data)
    return _summary(data)
