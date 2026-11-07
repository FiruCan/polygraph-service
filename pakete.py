"""
pakete.py
---------
Fragen-Pakete und ihre Antworten. Ein Paket ist eine JSON-Datei mit Fragen
zu einem Thema (fragen/<fachgebiet>/<name>.json, z.B. die Buffett-Fragen zu
Coca-Cola), die Argos nacheinander recherchiert. Nach jeder Frage schickt
Argos die Antwort hierher; sie landet im Datenordner der Instanz
(data/<fachgebiet>/antworten/<name>/<lauf>.json), ein Lauf pro Paket-Start.
So bleibt ein frueherer Lauf erhalten und laesst sich mit einem spaeteren
vergleichen.

Die Pakete liegen im Repo (von Hand geschrieben), die Antworten nicht (sie
entstehen aus dem Graphen und gehoeren zu ihm).
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


def load_paket(fragen_dir: str, name: str) -> dict:
    """-> Inhalt von <name>.json; FileNotFoundError, wenn es das Paket nicht gibt."""
    if not valid_name(name):
        raise FileNotFoundError(name)
    return _read(os.path.join(fragen_dir, name + ".json"))


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


def list_pakete(fragen_dir: str, antworten_dir: str) -> list:
    """Alle Pakete des Fachgebiets mit Zahl der Fragen und dem letzten Antwort-Lauf."""
    if not os.path.isdir(fragen_dir):
        return []
    pakete = []
    for file in sorted(os.listdir(fragen_dir)):
        name, ext = os.path.splitext(file)
        if ext != ".json" or not valid_name(name):
            continue
        try:
            data = _read(os.path.join(fragen_dir, file))
        except (OSError, ValueError):
            continue
        laeufe = list_laeufe(antworten_dir, name)
        pakete.append({"name": name, "titel": data.get("titel") or data.get("firma") or name,
                       "firma": data.get("firma"), "ticker": data.get("ticker"),
                       "anzahl": len(data.get("fragen") or []),
                       "letzter_lauf": laeufe[0] if laeufe else None})
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
