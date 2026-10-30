"""
translate_graph.py
------------------
Einmalige Umstellung des Bestands auf Englisch: Knotennamen, die Angaben
an den Kanten (Freitext-Angaben des Profils, GET /profile) und die Knotentypen. Neue
Tripel uebersetzt der Import selbst, siehe graph/translate.py. Arbeitet
ueber die API des laufenden Service - direkt in die graph.gml zu schreiben
wuerde der Service beim naechsten Speichern wieder ueberschreiben.

    python translate_graph.py plan               # Vorschlaege -> data/<fachgebiet>/translate_review.json
    python translate_graph.py plan --nur typen   # nur Teile pruefen: knoten, kanten, typen
    python translate_graph.py apply              # Backup, dann Freigegebenes uebernehmen

Die Review-Datei hat bis zu drei Listen, "knoten", "kanten" und "typen".
Man kann "neu" korrigieren oder "freigegeben" auf false setzen.
"zusammenfuehren": true heisst, der englische Name existiert schon (z.B.
"Multiple Sklerose" -> "multiple sclerosis") - dann werden die Knoten
vereint statt umbenannt; bei Typen tragen die Knoten danach denselben Typ.
"""

import argparse
import json
import os
import sys

import requests

from graph.translate import translate_details, translate_names, translate_types

HERE = os.path.dirname(os.path.abspath(__file__))
# data/<fachgebiet>/translate_review.json (review_path); fest gesetzt nur in Tests
REVIEW_PATH = None
CHUNK = 200
PARTS = ("knoten", "kanten", "typen")


def review_path(url: str) -> str:
    """Review-Datei im Datenordner der Instanz - zwei Instanzen kommen sich so nicht in die Quere."""
    if REVIEW_PATH:
        return REVIEW_PATH
    name = requests.get(f"{url}/profile", timeout=60).json()["name"]
    return os.path.join(HERE, "data", name, "translate_review.json")


def _progress(done, total):
    print(f"  {done}/{total}", end="\r")


def _renames(values: list, translated: dict) -> list:
    """
    Vorschlaege alt -> neu fuer Knotennamen bzw. Typen. Ein Ziel, das sich
    nur in Gross-/Kleinschreibung von einem bestehenden Wert unterscheidet,
    wird auf den bestehenden abgebildet.
    """
    existing = {v.casefold(): v for v in values}
    known = set(values)
    result = []
    for old in values:
        new = existing.get(translated[old].casefold(), translated[old])
        if new != old:
            result.append({"alt": old, "neu": new, "zusammenfuehren": new in known, "freigegeben": True})
    return result


def plan(url: str, parts=PARTS):
    # langer Timeout: GET /graph wartet, solange ein Import den Graphen sperrt
    graph = requests.get(f"{url}/graph", timeout=600).json()
    review = {}

    if "knoten" in parts:
        names = [n["id"] for n in graph["nodes"]]
        print(f"{len(names)} Knoten werden geprueft ...")
        review["knoten"] = _renames(names, translate_names(names, progress=_progress))
        print()

    if "kanten" in parts:
        # welche Kanten-Angaben Freitext sind, sagt das Profil der Instanz
        fields = [q["name"] for q in requests.get(f"{url}/profile", timeout=60).json()["qualifiers"]
                  if q["translate"]]
        texts = {(f, e[f]) for e in graph["edges"] for f in fields
                 if isinstance(e.get(f), str) and e[f].strip()}
        print(f"{len(texts)} Kanten-Angaben werden geprueft ...")
        details = translate_details(sorted({t for _, t in texts}), progress=_progress)
        print()
        review["kanten"] = [{"feld": f, "alt": t, "neu": details[t], "freigegeben": True}
                            for f, t in sorted(texts) if details[t] != t]

    if "typen" in parts:
        types = sorted({n["type"] for n in graph["nodes"] if n.get("type")})
        print(f"{len(types)} Knotentypen werden geprueft ...")
        review["typen"] = _renames(types, translate_types(types, progress=_progress))
        print()

    path = review_path(url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(review, f, ensure_ascii=False, indent=2)
    print("Vorschlaege - " + ", ".join(f"{part}: {len(items)}" for part, items in review.items())
          + f" -> {path}")
    for part in ("knoten", "typen"):
        merges = [r for r in review.get(part, []) if r["zusammenfuehren"]]
        if merges:
            print(f"davon Zusammenfuehrungen ({part}): {len(merges)}")
        for r in merges[:30]:
            print(f"  {r['alt']!r} -> {r['neu']!r}")


def apply(url: str):
    with open(review_path(url), encoding="utf-8") as f:
        review = json.load(f)
    renames = [r for r in review.get("knoten", []) if r.get("freigegeben")]
    rewrites = [r for r in review.get("kanten", []) if r.get("freigegeben")]
    retypes = [r for r in review.get("typen", []) if r.get("freigegeben")]
    if not renames and not rewrites and not retypes:
        sys.exit("Nichts freigegeben.")

    # Backup macht der Service selbst (POST /graph/backup): er speichert vorher
    # und kennt seinen Datenordner
    backup = requests.post(f"{url}/graph/backup", timeout=600).json()["backup"]
    print(f"Backup: {backup}")

    totals = {"renamed": 0, "merged": 0, "skipped": []}
    for i in range(0, len(renames), CHUNK):
        body = {"renames": [{"old": r["alt"], "new": r["neu"]} for r in renames[i:i + CHUNK]]}
        result = requests.post(f"{url}/nodes/rename", json=body, timeout=600).json()
        for key in totals:
            totals[key] += result[key]
    if renames:
        print(f"umbenannt: {totals['renamed']}, zusammengefuehrt: {totals['merged']}, "
              f"uebersprungen: {len(totals['skipped'])} - Graph jetzt {result['nodes']} Knoten, "
              f"{result['edges']} Kanten")
    for s in totals["skipped"]:
        print(f"  uebersprungen: {s['old']!r} -> {s['new']!r} ({s['reason']})")

    changed = 0
    for i in range(0, len(rewrites), CHUNK):
        body = {"rewrites": [{"field": r["feld"], "old": r["alt"], "new": r["neu"]}
                             for r in rewrites[i:i + CHUNK]]}
        changed += requests.post(f"{url}/edges/rewrite", json=body, timeout=600).json()["changed"]
    if rewrites:
        print(f"Kanten-Angaben geaendert: {changed}")

    retyped = 0
    for r in retypes:
        body = {"kind": "type", "old": r["alt"], "new": r["neu"]}
        retyped += requests.post(f"{url}/vocabulary/rename", json=body, timeout=600).json()["changed"]
    if retypes:
        print(f"Typen umbenannt: {len(retypes)}, an {retyped} Knoten")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["plan", "apply"])
    parser.add_argument("--nur", nargs="+", choices=PARTS, default=list(PARTS),
                        help="plan: nur diese Teile pruefen")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    if args.step == "plan":
        plan(url, args.nur)
    else:
        apply(url)
