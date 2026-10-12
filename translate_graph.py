"""
translate_graph.py
------------------
Einmalige Umstellung des Bestands auf Englisch: Knotennamen und die
Angaben an den Kanten (value, condition, evidence_level). Neue Tripel
uebersetzt der Import selbst, siehe graph/translate.py. Arbeitet ueber die
API des laufenden Service - direkt in data/graph.gml zu schreiben wuerde
der Service beim naechsten Speichern wieder ueberschreiben.

    python translate_graph.py plan    # Vorschlaege -> data/translate_review.json
    python translate_graph.py apply   # Backup, dann Freigegebenes uebernehmen

Die Review-Datei hat zwei Listen, "knoten" und "kanten". Man kann "neu"
korrigieren oder "freigegeben" auf false setzen. "zusammenfuehren": true
heisst, der englische Name existiert schon (z.B. "Multiple Sklerose" ->
"multiple sclerosis") - dann werden die Knoten vereint statt umbenannt.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

import requests

from graph.translate import DETAIL_FIELDS, translate_details, translate_names

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_PATH = os.path.join(HERE, "data", "translate_review.json")
GRAPH_PATH = os.path.join(HERE, "data", "graph.gml")
CHUNK = 200


def _progress(done, total):
    print(f"  {done}/{total}", end="\r")


def plan(url: str):
    # langer Timeout: GET /graph wartet, solange ein Import den Graphen sperrt
    graph = requests.get(f"{url}/graph", timeout=600).json()
    names = [n["id"] for n in graph["nodes"]]
    print(f"{len(names)} Knoten werden geprueft ...")
    translated = translate_names(names, progress=_progress)
    print()

    # Zielname, der sich nur in Gross-/Kleinschreibung von einem bestehenden
    # Knoten unterscheidet -> auf den bestehenden abbilden
    existing = {n.casefold(): n for n in names}
    renames = []
    for old in names:
        new = translated[old]
        new = existing.get(new.casefold(), new)
        if new != old:
            renames.append({"alt": old, "neu": new, "zusammenfuehren": new in existing.values(),
                            "freigegeben": True})

    texts = {(f, e[f]) for e in graph["edges"] for f in DETAIL_FIELDS
             if isinstance(e.get(f), str) and e[f].strip()}
    print(f"{len(texts)} Kanten-Angaben werden geprueft ...")
    details = translate_details(sorted({t for _, t in texts}), progress=_progress)
    print()
    rewrites = [{"feld": f, "alt": t, "neu": details[t], "freigegeben": True}
                for f, t in sorted(texts) if details[t] != t]

    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump({"knoten": renames, "kanten": rewrites}, f, ensure_ascii=False, indent=2)
    merges = [r for r in renames if r["zusammenfuehren"]]
    print(f"{len(renames)} Umbenennungen, davon {len(merges)} Zusammenfuehrungen, "
          f"{len(rewrites)} Kanten-Angaben -> {REVIEW_PATH}")
    for r in merges[:30]:
        print(f"  {r['alt']!r} -> {r['neu']!r}")


def apply(url: str):
    with open(REVIEW_PATH, encoding="utf-8") as f:
        review = json.load(f)
    renames = [r for r in review["knoten"] if r.get("freigegeben")]
    rewrites = [r for r in review["kanten"] if r.get("freigegeben")]
    if not renames and not rewrites:
        sys.exit("Nichts freigegeben.")

    backup = os.path.join(HERE, "data", f"graph.backup-{datetime.now():%Y-%m-%d-%H%M%S}.gml")
    shutil.copy2(GRAPH_PATH, backup)
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
    print(f"Kanten-Angaben geaendert: {changed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["plan", "apply"])
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    (plan if args.step == "plan" else apply)(args.url.rstrip("/"))
