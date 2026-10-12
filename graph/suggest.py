"""
suggest.py
----------
Beispielfragen aus dem Graphen erzeugen (GET /questions/suggest), damit man
sich nicht selbst Fragen ausdenken muss.

Zwei Schritte:
1. Ausgangspunkte aus der Graph-Struktur, ohne LLM - vier Arten:
   - "detail": eine Kante mit Bedingung, Wert oder Evidenz ("Unter welchen
     Umstaenden ...?", "Wie stark ...?")
   - "knoten": ein Knoten mit mehreren Kanten (viel Wissen dazu)
   - "pfad": zwei Knoten, die nur ueber 2-4 Zwischenschritte verbunden sind -
     das sind die Fragen, fuer die der Antwort-Agent (ask.py) mit seinen
     Werkzeugen gebaut ist
   - "vergleich": zwei Knoten, die auf dasselbe Ziel wirken
2. Ein LLM-Aufruf formuliert pro Ausgangspunkt eine natuerliche Frage - mit
   den zugehoerigen Fakten samt Bedingung/Wert/Evidenz im Prompt, damit die
   Frage ein konkretes Detail aufgreifen kann.

Weil jede Frage aus Kanten entsteht, die wirklich im Graphen stehen, ist sie
beantwortbar - ein frei erfindendes LLM wuerde oft Dinge fragen, zu denen der
Graph nichts weiss.

Gegen Wiederholungen: Knoten werden aus allen vernetzten Knoten gezogen
(gewichtet nach Wurzel des Grads - wichtige Begriffe oefter, aber ein
riesiger Hub dominiert nicht), und SuggestionHistory merkt sich die zuletzt
benutzten Ausgangspunkte. Die werden ausgelassen, bis nichts Neues mehr da
ist - dann beginnt der Verlauf von vorn. Scheitert der LLM-Aufruf, gibt es
Fragen aus einer festen Vorlage statt eines Fehlers.
"""

import json
import math
import os
import random
import threading
from collections import deque

import networkx as nx
import ollama

from graph.ask import DEFAULT_LANGUAGE

MODEL = "gemma4:26b"
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "suggest_questions.md")
MAX_FACTS = 6           # Fakten pro Knoten-Ausgangspunkt im Prompt
CONTEXT_FACTS = 2       # Zusatzfakten zum Subjekt bei "detail"
PATH_LENGTHS = (2, 4)   # Zwischenschritte fuer "pfad"-Fragen (min, max Kanten)
ATTEMPTS = 300          # Zufallsversuche pro Ausgangspunkt
HISTORY_SIZE = 300      # so viele zuletzt benutzte Ausgangspunkte werden ausgelassen
KINDS = ("detail", "pfad", "knoten", "vergleich")

QUESTIONS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"nr": {"type": "integer"}, "frage": {"type": "string", "minLength": 1}},
        "required": ["nr", "frage"],
    },
}


class SuggestionHistory:
    """Zuletzt vorgeschlagene Ausgangspunkte (thread-sicher, nur im Speicher)."""

    def __init__(self, size: int = HISTORY_SIZE):
        self._keys = deque(maxlen=size)
        self._lock = threading.Lock()

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._keys

    def add(self, key):
        with self._lock:
            self._keys.append(key)

    def clear(self):
        with self._lock:
            self._keys.clear()


HISTORY = SuggestionHistory()


def _fact(u, v, data) -> str:
    details = [f"{label}: {data[key]}" for key, label in
               (("value", "Wert"), ("condition", "Bedingung"), ("evidence_level", "Evidenz"))
               if data.get(key) not in (None, "")]
    return f"{u} --{data.get('relation')}--> {v}" + (f" [{'; '.join(details)}]" if details else "")


def _has_detail(data) -> bool:
    return any(data.get(k) not in (None, "") for k in ("value", "condition", "evidence_level"))


def _node_facts(graph, node, rng) -> list:
    edges = list(graph.out_edges(node, data=True)) + list(graph.in_edges(node, data=True))
    # Kanten mit Details zuerst, sonst zufaellig - so sieht jede Frage zum
    # selben Knoten andere Fakten.
    rng.shuffle(edges)
    edges.sort(key=lambda e: not _has_detail(e[2]))
    return [_fact(u, v, d) for u, v, d in edges[:MAX_FACTS]]


def _path_facts(graph, path: list) -> list:
    """Je eine Kante pro Schritt - in welcher Richtung auch immer sie im Graphen steht."""
    facts = []
    for a, b in zip(path, path[1:]):
        if graph.has_edge(a, b):
            facts.append(_fact(a, b, next(iter(graph[a][b].values()))))
        else:
            facts.append(_fact(b, a, next(iter(graph[b][a].values()))))
    return facts


def _weighted_pick(rng, nodes, weights, exclude):
    pool = [(n, w) for n, w in zip(nodes, weights) if n not in exclude]
    if not pool:
        return None
    return rng.choices([n for n, _ in pool], weights=[w for _, w in pool])[0]


class _SeedFinder:
    def __init__(self, graph, rng, history):
        self.graph = graph
        self.rng = rng
        self.history = history
        self.undirected = graph.to_undirected(as_view=True)
        self.nodes = [n for n in graph.nodes if graph.degree(n) >= 2] or list(graph.nodes)
        self.weights = [math.sqrt(graph.degree(n)) for n in self.nodes]
        self.detail_edges = [(u, v, d) for u, v, d in graph.edges(data=True) if _has_detail(d)]
        self.used_nodes = set()   # in dieser Runde schon Ausgangspunkt
        self.used_keys = set()

    def _fresh(self, key) -> bool:
        return key not in self.used_keys and key not in self.history

    def _take(self, key, seed):
        self.used_keys.add(key)
        self.used_nodes.update(seed["knoten"])
        return seed

    def detail(self):
        if not self.detail_edges:
            return None
        for _ in range(ATTEMPTS):
            u, v, d = self.rng.choice(self.detail_edges)
            key = ("detail", u, d.get("relation"), v)
            if not self._fresh(key) or u in self.used_nodes or v in self.used_nodes:
                continue
            main = _fact(u, v, d)
            context = [f for f in _node_facts(self.graph, u, self.rng) if f != main][:CONTEXT_FACTS]
            return self._take(key, {"art": "detail", "knoten": [u, v], "fakten": [main] + context})
        return None

    def knoten(self):
        skipped = set()
        for _ in range(ATTEMPTS):
            node = _weighted_pick(self.rng, self.nodes, self.weights, self.used_nodes | skipped)
            if node is None:
                return None
            key = ("knoten", node)
            if not self._fresh(key):
                skipped.add(node)
                continue
            return self._take(key, {"art": "knoten", "knoten": [node],
                                    "fakten": _node_facts(self.graph, node, self.rng)})
        return None

    def pfad(self):
        for _ in range(ATTEMPTS):
            a = _weighted_pick(self.rng, self.nodes, self.weights, self.used_nodes)
            b = _weighted_pick(self.rng, self.nodes, self.weights, self.used_nodes | {a})
            if a is None or b is None:
                return None
            key = ("pfad", frozenset((a, b)))
            if not self._fresh(key):
                continue
            try:
                path = nx.shortest_path(self.undirected, a, b)
            except nx.NetworkXNoPath:
                continue
            if PATH_LENGTHS[0] <= len(path) - 1 <= PATH_LENGTHS[1]:
                return self._take(key, {"art": "pfad", "knoten": [a, b], "fakten": _path_facts(self.graph, path)})
        return None

    def vergleich(self):
        """Zwei Knoten mit Kante auf dasselbe Ziel: 'Wirken A und B gleich auf C?'"""
        for _ in range(ATTEMPTS):
            target = _weighted_pick(self.rng, self.nodes, self.weights, self.used_nodes)
            if target is None:
                return None
            incoming = {}
            for u, _, d in self.graph.in_edges(target, data=True):
                if u != target and u not in self.used_nodes:
                    incoming.setdefault(u, d)
            if len(incoming) < 2:
                continue
            a, b = self.rng.sample(sorted(incoming), 2)
            key = ("vergleich", frozenset((a, b)), target)
            if not self._fresh(key):
                continue
            facts = [_fact(a, target, incoming[a]), _fact(b, target, incoming[b])]
            return self._take(key, {"art": "vergleich", "knoten": [a, b, target], "fakten": facts})
        return None


def find_seeds(graph, count: int = 5, rng: random.Random = None, history: SuggestionHistory = None) -> list:
    """
    Ausgangspunkte, reihum aus den vier Arten (Startart zufaellig). Was im
    Verlauf steht, wird ausgelassen; ist dadurch gar nichts mehr zu finden,
    wird der Verlauf geleert und neu begonnen.
    """
    rng = rng or random.Random()
    history = history if history is not None else SuggestionHistory()
    if graph.number_of_edges() == 0:
        return []

    for attempt in range(2):
        finder = _SeedFinder(graph, rng, history)
        kinds = list(KINDS)
        rng.shuffle(kinds)
        seeds, misses, i = [], 0, 0
        while len(seeds) < count and misses < len(kinds):
            seed = getattr(finder, kinds[i % len(kinds)])()
            i += 1
            if seed:
                seeds.append(seed)
                misses = 0
            else:
                misses += 1
        if seeds or attempt:
            break
        history.clear()  # alles schon vorgeschlagen - von vorn

    for key in finder.used_keys:
        history.add(key)
    return seeds


def fallback_question(seed: dict) -> str:
    """Feste Vorlage, falls der LLM-Aufruf scheitert - englisch wie der Graph."""
    k = seed["knoten"]
    if seed["art"] == "pfad":
        return f"How are {k[0]} and {k[1]} connected?"
    if seed["art"] == "detail":
        return f"Under which conditions is {k[0]} related to {k[1]}?"
    if seed["art"] == "vergleich":
        return f"Do {k[0]} and {k[1]} affect {k[2]} in the same way?"
    return f"What is known about {k[0]}?"


def build_prompt(seeds: list, language: str = DEFAULT_LANGUAGE) -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    blocks = []
    for i, s in enumerate(seeds, 1):
        k = s["knoten"]
        if s["art"] == "pfad":
            what = f"von {k[0]} nach {k[1]}"
        elif s["art"] == "detail":
            what = f"{k[0]} -> {k[1]}"
        elif s["art"] == "vergleich":
            what = f"{k[0]} vs. {k[1]}, Ziel {k[2]}"
        else:
            what = k[0]
        blocks.append(f"{i}. Art: {s['art']} | {what}\n" + "\n".join(f"   - {f}" for f in s["fakten"]))
    return template.format(seeds="\n".join(blocks), language=language)


def suggest_questions(graph, count: int = 5, rng: random.Random = None,
                      history: SuggestionHistory = None, language: str = DEFAULT_LANGUAGE) -> list:
    seeds = find_seeds(graph, count, rng, HISTORY if history is None else history)
    if not seeds:
        return []

    texts = {}
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": build_prompt(seeds, language)}],
            think=False,
            format=QUESTIONS_SCHEMA,
            options={"num_predict": 2000, "temperature": 0.9},
        )
        for item in json.loads(response["message"]["content"]):
            texts[item["nr"]] = item["frage"].strip()
    except Exception as e:  # Vorschlaege sind ein Komfort - lieber Vorlage als Fehler
        print(f"Warnung: Fragen-Formulierung fehlgeschlagen ({e}), nutze Vorlage")

    return [
        {"question": texts.get(i) or fallback_question(s), "type": s["art"], "nodes": s["knoten"]}
        for i, s in enumerate(seeds, 1)
    ]
