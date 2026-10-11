"""
suggest.py
----------
Beispielfragen aus dem Graphen erzeugen (GET /questions/suggest), damit man
sich nicht selbst Fragen ausdenken muss.

Zwei Schritte:
1. Ausgangspunkte aus der Graph-Struktur, ohne LLM:
   - "knoten": stark vernetzte Knoten (viele Kanten = viel Wissen dazu)
   - "pfad": zwei Knoten, die nur ueber 2-4 Zwischenschritte verbunden sind -
     das sind die Fragen, fuer die der Antwort-Agent (ask.py) mit seinen
     Werkzeugen gebaut ist
2. Ein LLM-Aufruf formuliert pro Ausgangspunkt eine natuerliche Frage - mit
   den zugehoerigen Fakten im Prompt.

Weil jede Frage aus Kanten entsteht, die wirklich im Graphen stehen, ist sie
beantwortbar - ein frei erfindendes LLM wuerde oft Dinge fragen, zu denen der
Graph nichts weiss.

Die Auswahl ist zufaellig (aus den Top-Knoten bzw. passenden Paaren), damit
jeder Klick auf "Fragen vorschlagen" andere Vorschlaege bringt. Scheitert der
LLM-Aufruf, gibt es Fragen aus einer festen Vorlage statt eines Fehlers.
"""

import json
import os
import random

import networkx as nx
import ollama

MODEL = "gemma4:26b"
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "suggest_questions.md")
TOP_NODES = 10          # aus so vielen der am staerksten vernetzten Knoten wird gezogen
MAX_FACTS = 6           # Fakten pro Knoten-Ausgangspunkt im Prompt
PATH_LENGTHS = (2, 4)   # Zwischenschritte fuer "pfad"-Fragen (min, max Kanten)
PAIR_ATTEMPTS = 300

QUESTIONS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"nr": {"type": "integer"}, "frage": {"type": "string", "minLength": 1}},
        "required": ["nr", "frage"],
    },
}


def _fact(u, v, data) -> str:
    return f"{u} --{data.get('relation')}--> {v}"


def _node_facts(graph, node) -> list:
    out = [_fact(u, v, d) for u, v, d in graph.out_edges(node, data=True)]
    inc = [_fact(u, v, d) for u, v, d in graph.in_edges(node, data=True)]
    return (out + inc)[:MAX_FACTS]


def _path_facts(graph, path: list) -> list:
    """Je eine Kante pro Schritt - in welcher Richtung auch immer sie im Graphen steht."""
    facts = []
    for a, b in zip(path, path[1:]):
        if graph.has_edge(a, b):
            facts.append(_fact(a, b, next(iter(graph[a][b].values()))))
        else:
            facts.append(_fact(b, a, next(iter(graph[b][a].values()))))
    return facts


def find_seeds(graph, count: int = 5, rng: random.Random = None) -> list:
    """Ausgangspunkte: etwa die Haelfte Knoten-, die andere Haelfte Pfad-Fragen."""
    rng = rng or random.Random()
    if graph.number_of_edges() == 0:
        return []

    by_degree = sorted(graph.nodes, key=lambda n: graph.degree(n), reverse=True)
    hubs = by_degree[:TOP_NODES]
    n_paths = count // 2
    seeds = []

    undirected = graph.to_undirected(as_view=True)
    candidates = [n for n in by_degree if graph.degree(n) >= 2] or list(graph.nodes)
    seen_pairs = set()
    for _ in range(PAIR_ATTEMPTS):
        if len(seeds) >= n_paths or len(candidates) < 2:
            break
        a, b = rng.sample(candidates, 2)
        if frozenset((a, b)) in seen_pairs:
            continue
        seen_pairs.add(frozenset((a, b)))
        try:
            path = nx.shortest_path(undirected, a, b)
        except nx.NetworkXNoPath:
            continue
        if PATH_LENGTHS[0] <= len(path) - 1 <= PATH_LENGTHS[1]:
            seeds.append({"art": "pfad", "knoten": [a, b], "fakten": _path_facts(graph, path)})

    used = {n for s in seeds for n in s["knoten"]}
    for node in rng.sample(hubs, len(hubs)):
        if len(seeds) >= count:
            break
        if node not in used:
            seeds.append({"art": "knoten", "knoten": [node], "fakten": _node_facts(graph, node)})
            used.add(node)
    return seeds


def fallback_question(seed: dict) -> str:
    if seed["art"] == "pfad":
        return f"Wie hängen {seed['knoten'][0]} und {seed['knoten'][1]} zusammen?"
    return f"Was ist über {seed['knoten'][0]} bekannt?"


def build_prompt(seeds: list) -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    blocks = []
    for i, s in enumerate(seeds, 1):
        head = f"{i}. Art: {s['art']} | " + (
            f"von {s['knoten'][0]} nach {s['knoten'][1]}" if s["art"] == "pfad" else s["knoten"][0])
        blocks.append(head + "\n" + "\n".join(f"   - {f}" for f in s["fakten"]))
    return template.format(seeds="\n".join(blocks))


def suggest_questions(graph, count: int = 5, rng: random.Random = None) -> list:
    seeds = find_seeds(graph, count, rng)
    if not seeds:
        return []

    texts = {}
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": build_prompt(seeds)}],
            think=False,
            format=QUESTIONS_SCHEMA,
            options={"num_predict": 1500},
        )
        for item in json.loads(response["message"]["content"]):
            texts[item["nr"]] = item["frage"].strip()
    except Exception as e:  # Vorschlaege sind ein Komfort - lieber Vorlage als Fehler
        print(f"Warnung: Fragen-Formulierung fehlgeschlagen ({e}), nutze Vorlage")

    return [
        {"question": texts.get(i) or fallback_question(s), "type": s["art"], "nodes": s["knoten"]}
        for i, s in enumerate(seeds, 1)
    ]
