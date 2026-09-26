"""
ask.py
------
Fragen an den Wissensgraphen (GraphRAG mit lokalem Ollama):
1. Das LLM waehlt aus den Knotennamen die zur Frage passenden aus.
2. Dazu werden deren Kanten (bis 2 Schritte) und Verbindungspfade zwischen den
   gewaehlten Knoten aus dem Graphen geholt.
3. Das LLM antwortet nur anhand dieser Tripel und nennt sie als Beleg.

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


def ask(graph, question: str) -> dict:
    """
    Fuehrt den GraphRAG-Ablauf aus und gibt ein API-taugliches Dict zurueck:
    question, selected_nodes, answer, triples (nummeriert), graph (Teilgraph
    im GraphStore.to_json()-Format).
    """
    from graph.store import GraphStore  # lokal importiert, um Zirkularimport zu vermeiden

    selected = select_nodes(graph, question)
    if not selected:
        return {
            "question": question, "selected_nodes": [], "answer": "Kein passender Knoten im Graphen gefunden.",
            "triples": [], "graph": {"nodes": [], "edges": []},
        }

    edges = collect_edges(graph, selected)
    if not edges:
        return {
            "question": question, "selected_nodes": selected,
            "answer": f"Gewaehlte Knoten {selected} haben keine Kanten.",
            "triples": [], "graph": {"nodes": [], "edges": []},
        }

    triple_lines = [format_triple(i, graph, e) for i, e in enumerate(edges, 1)]
    # think=True fuer die Antwort (anders als select_nodes): das Modell muss
    # abwaegen, ob sich aus den Tripeln + Fachwissen eine gekennzeichnete
    # Ableitung ziehen laesst (siehe ask_answer.md) - ohne den Denkschritt
    # fiel es sonst reflexhaft auf "Das steht nicht im Graphen" zurueck,
    # auch wenn eine plausible Ableitung moeglich gewesen waere.
    answer = _chat(_load_prompt("ask_answer.md").format(
        triples="\n".join(triple_lines), question=question
    ), think=True, num_predict=6000)

    triples = []
    for i, e in enumerate(edges, 1):
        u, v, k = e
        data = graph.edges[e]
        triples.append({
            "n": i, "subject": u, "relation": data.get("relation"), "object": v,
            "value": data.get("value"), "condition": data.get("condition"),
            "evidence_level": data.get("evidence_level"), "confidence": data.get("confidence"),
        })

    subgraph_store = GraphStore()
    subgraph_store.graph = build_subgraph(graph, edges)

    return {
        "question": question,
        "selected_nodes": selected,
        "answer": answer,
        "triples": triples,
        "graph": subgraph_store.to_json(),
    }
