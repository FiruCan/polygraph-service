"""
ask.py
------
Fragen an den Wissensgraphen (GraphRAG mit lokalem Ollama):
1. Das LLM waehlt aus den Knotennamen die zur Frage passenden aus.
2. Dazu werden deren Kanten (bis 2 Schritte) und Verbindungspfade zwischen den
   gewaehlten Knoten aus dem Graphen geholt.
3. Ein Agent antwortet anhand dieser Tripel und nennt sie als Beleg. Reichen
   sie nicht, darf er per Werkzeug (suche_knoten, kanten_von, pfad) weitere
   Tripel nachladen - bis zu MAX_TOOL_ROUNDS Runden. Nachgeladene Tripel
   werden fortlaufend weiternummeriert, damit Belege eindeutig bleiben.

ask() gibt ein Dict zurueck (fuer die API); Druckausgabe/HTML-Erzeugung
passiert nicht mehr hier, das macht das Frontend aus der JSON-Antwort.
"""

import json
import os
from itertools import combinations

import networkx as nx
import ollama

MODEL = "gemma4:26b"
HOPS = 2
MAX_PATH_LENGTH = 4
MAX_TRIPLES = 100
MAX_TOOL_ROUNDS = 4
MAX_TOOL_TRIPLES = 40     # pro Werkzeugaufruf
MAX_TOTAL_TRIPLES = 250   # Obergrenze ueber alle Runden
MAX_SEARCH_HITS = 30
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPT_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def _chat(prompt: str, think: bool = False, num_predict: int = 4000) -> str:
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=think,
        options={"num_predict": num_predict},
    )
    return response["message"]["content"].strip()


def select_nodes(graph, question: str) -> list:
    """Laesst das LLM die zur Frage passenden Knoten waehlen (nur existierende Namen)."""
    prompt = _load_prompt("ask_select.md").format(
        nodes="\n".join(f"- {n}" for n in graph.nodes), question=question
    )
    raw = _chat(prompt).removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        names = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [n for n in names if n in graph.nodes]


def collect_edges(graph, selected: list) -> list:
    """Kanten bis HOPS Schritte um die gewaehlten Knoten plus Kanten auf kurzen Pfaden zwischen ihnen."""
    distance = {}  # Kante -> Abstand zum naechsten gewaehlten Knoten (0 = am naechsten)
    frontier = set(selected)
    seen = set(selected)
    for hop in range(HOPS):
        reached = set()
        for node in frontier:
            for edge in list(graph.in_edges(node, keys=True)) + list(graph.out_edges(node, keys=True)):
                distance.setdefault(edge, hop)
                reached.update((edge[0], edge[1]))
        frontier = reached - seen
        seen |= reached

    undirected = graph.to_undirected(as_view=True)
    for a, b in combinations(selected, 2):
        try:
            path = nx.shortest_path(undirected, a, b)
        except nx.NetworkXNoPath:
            continue
        if len(path) - 1 > MAX_PATH_LENGTH:
            continue
        for x, y in zip(path, path[1:]):
            for u, v in ((x, y), (y, x)):
                if graph.has_edge(u, v):
                    for k in graph[u][v]:
                        distance[(u, v, k)] = 0

    ranked = sorted(distance, key=lambda e: (distance[e], -float(graph.edges[e].get("confidence", 0))))
    return ranked[:MAX_TRIPLES]


def format_triple(number: int, graph, edge) -> str:
    u, v, k = edge
    data = graph.edges[edge]
    parts = [f"[{number}] {u} --{data.get('relation')}--> {v}"]
    for key, label in (("value", "value"), ("condition", "condition"),
                       ("evidence_level", "evidence"), ("confidence", "confidence")):
        if data.get(key) is not None:
            parts.append(f"{label}: {data[key]}")
    return " | ".join(parts)


def build_subgraph(graph, edges: list):
    sub = nx.MultiDiGraph()
    for u, v, k in edges:
        sub.add_node(u, **graph.nodes[u])
        sub.add_node(v, **graph.nodes[v])
        sub.add_edge(u, v, key=k, **graph.edges[(u, v, k)])
    return sub


TOOLS = [
    {"type": "function", "function": {
        "name": "suche_knoten",
        "description": "Sucht Knotennamen im Graphen, die den Begriff enthalten (Teilstring, "
                       "Gross-/Kleinschreibung egal). Fuer Synonyme mehrere Begriffe nacheinander probieren.",
        "parameters": {"type": "object", "required": ["begriff"],
                       "properties": {"begriff": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "kanten_von",
        "description": "Liefert alle ein- und ausgehenden Tripel eines Knotens (exakter Knotenname).",
        "parameters": {"type": "object", "required": ["knoten"],
                       "properties": {"knoten": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "pfad",
        "description": "Liefert die Tripel auf dem kuerzesten Weg zwischen zwei Knoten "
                       "(Richtung egal, exakte Knotennamen).",
        "parameters": {"type": "object", "required": ["von", "nach"],
                       "properties": {"von": {"type": "string"}, "nach": {"type": "string"}}},
    }},
]


class _Evidence:
    """Nummerierte Beleg-Liste: jede Kante bekommt genau eine feste Nummer, auch wenn sie mehrfach auftaucht."""

    def __init__(self, graph):
        self.graph = graph
        self.edges = []
        self.number = {}

    def add(self, edges) -> list:
        """Nimmt Kanten auf und gibt ihre Tripel-Zeilen zurueck (bekannte Kanten mit alter Nummer)."""
        lines = []
        for e in edges:
            if e not in self.number:
                if len(self.edges) >= MAX_TOTAL_TRIPLES:
                    lines.append("(Obergrenze an Tripeln erreicht, weitere werden nicht geladen.)")
                    break
                self.edges.append(e)
                self.number[e] = len(self.edges)
            lines.append(format_triple(self.number[e], self.graph, e))
        return lines


def _tool_search(graph, begriff: str) -> tuple:
    needle = str(begriff).casefold()
    hits = [n for n in graph.nodes if needle in str(n).casefold()][:MAX_SEARCH_HITS]
    if not hits:
        return f"Kein Knoten enthaelt '{begriff}'.", []
    return "Gefundene Knoten:\n" + "\n".join(f"- {n}" for n in hits), []


def _tool_edges(graph, evidence: _Evidence, knoten: str) -> tuple:
    if knoten not in graph.nodes:
        return f"Knoten '{knoten}' existiert nicht - erst mit suche_knoten den exakten Namen finden.", []
    edges = list(graph.in_edges(knoten, keys=True)) + list(graph.out_edges(knoten, keys=True))
    edges.sort(key=lambda e: -float(graph.edges[e].get("confidence", 0)))
    lines = evidence.add(edges[:MAX_TOOL_TRIPLES])
    return ("\n".join(lines) if lines else f"'{knoten}' hat keine Kanten."), [knoten]


def _tool_path(graph, evidence: _Evidence, von: str, nach: str) -> tuple:
    missing = [n for n in (von, nach) if n not in graph.nodes]
    if missing:
        return f"Knoten existiert nicht: {missing} - erst mit suche_knoten den exakten Namen finden.", []
    try:
        path = nx.shortest_path(graph.to_undirected(as_view=True), von, nach)
    except nx.NetworkXNoPath:
        return f"Keine Verbindung zwischen '{von}' und '{nach}'.", []
    edges = []
    for x, y in zip(path, path[1:]):
        for u, v in ((x, y), (y, x)):
            if graph.has_edge(u, v):
                edges.extend((u, v, k) for k in graph[u][v])
    return "\n".join(evidence.add(edges)), [von, nach]


def _run_tool(graph, evidence: _Evidence, name: str, args: dict) -> tuple:
    """Fuehrt einen Werkzeugaufruf aus -> (Text fuers Modell, Knoten, die in den Fokus ruecken)."""
    try:
        if name == "suche_knoten":
            return _tool_search(graph, args["begriff"])
        if name == "kanten_von":
            return _tool_edges(graph, evidence, args["knoten"])
        if name == "pfad":
            return _tool_path(graph, evidence, args["von"], args["nach"])
    except KeyError as missing:
        return f"Fehlendes Argument {missing} fuer {name}.", []
    return f"Unbekanntes Werkzeug '{name}'.", []


def _agent_answer(graph, question: str, evidence: _Evidence) -> tuple:
    """
    Antwort-Schleife: das Modell bekommt die Start-Tripel und darf bis zu
    MAX_TOOL_ROUNDS Mal Werkzeuge aufrufen. think=True (anders als
    select_nodes): das Modell muss abwaegen, ob die Tripel reichen, ob es
    nachladen soll und ob sich eine gekennzeichnete Ableitung ziehen laesst
    (siehe ask_answer.md) - ohne Denkschritt fiel es sonst reflexhaft auf
    "Das steht nicht im Graphen" zurueck. Gibt (Antwort, Schritte, Fokus-Knoten) zurueck.
    """
    start = "\n".join(format_triple(i, graph, e) for i, e in enumerate(evidence.edges, 1))
    messages = [{"role": "user", "content": _load_prompt("ask_answer.md").format(
        triples=start or "(keine - nutze die Werkzeuge)", question=question,
    )}]
    steps, focus = [], []

    for round_ in range(MAX_TOOL_ROUNDS + 1):
        last = round_ == MAX_TOOL_ROUNDS
        if last:
            messages.append({"role": "user", "content":
                             "Keine weiteren Werkzeugaufrufe moeglich. Antworte jetzt mit den vorhandenen Tripeln."})
        response = ollama.chat(
            model=MODEL, messages=messages, tools=None if last else TOOLS,
            think=True, options={"num_predict": 6000},
        )
        message = response["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return (message.get("content") or "").strip(), steps, focus

        messages.append(message)
        for call in calls:
            name, args = call["function"]["name"], dict(call["function"]["arguments"] or {})
            before = len(evidence.edges)
            text, nodes = _run_tool(graph, evidence, name, args)
            focus.extend(n for n in nodes if n not in focus)
            steps.append({"tool": name, "args": args, "new_triples": len(evidence.edges) - before})
            messages.append({"role": "tool", "tool_name": name, "content": text})

    return "", steps, focus  # nicht erreichbar: die letzte Runde laeuft ohne Werkzeuge


def ask(graph, question: str) -> dict:
    """
    Fuehrt den GraphRAG-Ablauf aus und gibt ein API-taugliches Dict zurueck:
    question, selected_nodes (Startknoten + vom Agenten untersuchte Knoten),
    answer, triples (nummeriert), graph (Teilgraph im GraphStore.to_json()-
    Format), steps (Werkzeugaufrufe des Agenten).
    """
    from graph.store import GraphStore  # lokal importiert, um Zirkularimport zu vermeiden

    selected = select_nodes(graph, question)
    evidence = _Evidence(graph)
    evidence.add(collect_edges(graph, selected) if selected else [])

    # Auch ohne Startknoten laeuft der Agent: er kann per suche_knoten
    # selbst Einstiegspunkte finden, die select_nodes uebersehen hat.
    answer, steps, focus = _agent_answer(graph, question, evidence)

    triples = []
    for i, e in enumerate(evidence.edges, 1):
        u, v, k = e
        data = graph.edges[e]
        triples.append({
            "n": i, "subject": u, "relation": data.get("relation"), "object": v,
            "value": data.get("value"), "condition": data.get("condition"),
            "evidence_level": data.get("evidence_level"), "confidence": data.get("confidence"),
            "origin": data.get("origin"),
        })

    subgraph_store = GraphStore()
    subgraph_store.graph = build_subgraph(graph, evidence.edges)

    # Nur Knoten melden, die im Teilgraphen vorkommen - das Frontend
    # zeichnet selected_nodes als Startpunkte und kennt sonst keinen Typ.
    in_subgraph = set(subgraph_store.graph.nodes)
    highlighted = [n for n in selected + [n for n in focus if n not in selected] if n in in_subgraph]

    return {
        "question": question,
        "selected_nodes": highlighted,
        "answer": answer,
        "triples": triples,
        "graph": subgraph_store.to_json(),
        "steps": steps,
    }
