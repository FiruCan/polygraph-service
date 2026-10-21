"""
dedupe.py
---------
Duplikat-Aufraeumer: durchsucht den ganzen Graphen nach Knoten, die dieselbe
Entitaet bezeichnen, aber beim Import nicht zusammengefuehrt wurden (z.B.
"MS" und "multiple sclerosis", "viral infections" und "viral infection"). Die
Synonym-Zusammenfuehrung in normalize.py greift nur beim Import und haengt
von der Reihenfolge ab - was dort durchrutscht, findet erst dieser Lauf.

Freigabe ohne Menschen: ein Vorschlag ist freigegeben ("freigegeben": true),
wenn Agent UND Graphdaten uebereinstimmen. Die Namen muessen belegen, dass
beide dasselbe sind (evidence: gleiche Woerter in anderer Schreibweise, oder
jeder Buchstabe der Abkuerzung ist ein Wortanfang der Langform); passt eine
Abkuerzung auf mehrere Langformen ("MS": multiple sclerosis, muscle
strength, ...), muss die gewaehlte mehr gemeinsame Nachbarn im Graphen
haben als jede andere (_rivals). Kein Allgemeinwissen: der Prompt verlangt
dasselbe, aber das lokale Modell haelt sich nicht immer daran (live: "MBI
ist ein Tippfehler fuer BMI") - deshalb prueft der Code nach. Umgekehrt
legt das Modell sein Veto bei Buchstaben-Zufaellen ein, die die Namen nicht
erkennen ("DAMPs" / "disease-associated microglia profiles").
polygraph/dedupe.py --auto fuehrt alle freigegebenen nach einem Backup
zusammen (POST /graph/backup, POST /nodes/merge).

Ablauf (wie beim Import, nur ueber alle Knoten):
1. Embeddings aller Knoten (bge-m3, in Paketen - ~36 s fuer 3.000 Knoten).
2. Pro Knoten die aehnlichsten anderen Knoten als Kandidaten. Bewusst
   strenger als beim Import (CANDIDATE_THRESHOLD 0.55): ueber alle
   Knotenpaare waeren das ~68.000 Paare, bei 0.75 und hoechstens 5
   Kandidaten ~1.300 Richter-Aufrufe. Abkuerzungen bekommen die
   Import-Schwelle und mehr Kandidaten, weil das Embedding sie schlecht
   erkennt: "MS" ~ "multiple Sklerose" nur 0.66, "MS symptoms" 0.75.
   Dazu kommen Knoten, deren Namen den Knoten belegen (name_partners, ~3 s):
   so steht "multiple sclerosis" sicher unter den Kandidaten von "MS".
3. Ein Richter-Agent (judge) entscheidet, ob einer der Kandidaten dieselbe
   Entitaet ist. Ein Paar wird nur einmal geprueft (A mit B, nicht danach
   noch B mit A).

Agent statt eines einzelnen Aufrufs wie beim Import (normalize.judge_verdict):
der darf nur unter den Kandidaten waehlen, und bei Abkuerzungen fehlt dort
oft die Langform ("MS": 20 Kandidaten von "MS diagnosis" bis "relapsing
MS", "multiple sclerosis" ist nicht dabei). Der Agent darf per Ollama Tool
Calling (wie der Frage-Agent in ask.py, ohne Framework) mit suche_knoten
danach suchen und endet mit dem Werkzeug urteil. Ruft er es nicht auf
(Klartext statt Werkzeug, MAX_TOOL_ROUNDS aufgebraucht), erzwingt ein
letzter Aufruf ohne Werkzeuge das Urteil per JSON-Schema. Treffer kann nur
ein Knoten sein, den er gesehen hat (Kandidat oder Suchergebnis) -
erfundene Namen fallen weg. Die Schleife ueber alle Knoten bleibt bewusst
im Code: sie muss JEDEN Knoten erfassen, ein frei laufender Agent wuerde
welche auslassen.

Bewusst nur die Suche: eine erste Fassung hatte zusaetzlich kanten_von
(Tripel eines Knotens) und zeigte Typen im Prompt. Live schaute sie fast
immer nach, brauchte doppelt so lange wie der alte Richter und erklaerte
danach Verwandtes fuer "im Kontext synonym" ("Stress" -> "psychological
stress", "Helicobacter pylori" -> "Helicobacter pylori infection"); ein
falsch vergebener Typ machte "HLA-A*02" zu "H2-aa". Die Funde bei
Abkuerzungen kamen aus der Suche, die Kanten brachten vor allem
Fehlvorschlaege (siehe PROGRESS.md).

Vorschlag: bei Abkuerzung und Langform bleibt die Langform (Antworten sind
fuer Laien), sonst der Knoten mit mehr Kanten (der etabliertere Name), bei
Gleichstand der vom Richter gewaehlte. "schritte" zeigt, was der
Agent gesucht hat, "beleg", worauf sich die Freigabe stuetzt, "mehrdeutig"
die Langformen, die bei den Nachbarn gleichauf lagen.
"""

import json
import os
import re
import time
from collections import defaultdict
from typing import Callable, Optional

import numpy as np
import ollama

from graph.normalize import CANDIDATE_THRESHOLD, EMBED_MODEL, JUDGE_MODEL, judge_schema

DEDUPE_THRESHOLD = 0.75
MAX_CANDIDATES = 5
ABBREVIATION_THRESHOLD = CANDIDATE_THRESHOLD
ABBREVIATION_MAX_CANDIDATES = 20
EMBED_BATCH = 64
MAX_TOOL_ROUNDS = 3
MAX_SEARCH_HITS = 20
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "dedupe_judge.md")
FORCE_VERDICT = ('Keine weiteren Werkzeuge. Antworte jetzt als JSON: zuerst "begruendung" '
                 '(ein kurzer Satz), dann "treffer" (exakter Knotenname oder null).')
# Fuellwoerter einer Langform, die keinen Buchstaben zur Abkuerzung beitragen muessen ("NLR" = neutrophil-to-lymphocyte ratio)
STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
WORD = r"[^\W_]+\+?"
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa"}

TOOLS = [
    {"type": "function", "function": {
        "name": "suche_knoten",
        "description": "Sucht Knotennamen, die den Begriff enthalten (Teilstring, Gross-/Kleinschreibung "
                       "und Bindestriche egal, kuerzeste zuerst). Knotennamen sind meist englisch.",
        "parameters": {"type": "object", "required": ["begriff"],
                       "properties": {"begriff": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "urteil",
        "description": "Dein Ergebnis, genau einmal am Ende: erst die Begruendung, dann der Treffer.",
        "parameters": {"type": "object", "required": ["begruendung", "treffer"], "properties": {
            "begruendung": {"type": "string", "description": "ein kurzer Satz"},
            "treffer": {"type": "string",
                        "description": "exakter Name des Knotens, der DASSELBE ist - leer, wenn keiner"},
        }},
    }},
]


def is_abbreviation(name: str) -> bool:
    """Kurz, ein Wort, mind. zwei Grossbuchstaben: MS, IL-6, OPCs, BDNF."""
    return len(name) <= 8 and " " not in name and sum(c.isupper() for c in name) >= 2


def embed_all(names: list) -> np.ndarray:
    """Normierte Embeddings (N, D) - in Paketen statt einzeln, ~4x schneller."""
    vectors = []
    for i in range(0, len(names), EMBED_BATCH):
        vectors += ollama.embed(model=EMBED_MODEL, input=names[i:i + EMBED_BATCH])["embeddings"]
    matrix = np.array(vectors, dtype=np.float32)
    return matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)


def _fold(text: str) -> str:
    """Fuer die Suche: Gross-/Kleinschreibung und Bindestriche egal ("brain derived" findet "Brain-Derived")."""
    return " ".join(re.sub(r"[-‐-―_]", " ", str(text).casefold()).split())


def _tool_search(graph, begriff: str) -> tuple:
    # kuerzeste Namen zuerst: "multiple sclerosis" vor Studientiteln, die es enthalten
    needle = _fold(begriff)
    hits = sorted((n for n in graph.nodes if needle and needle in _fold(n)),
                  key=lambda n: len(str(n)))[:MAX_SEARCH_HITS]
    if not hits:
        return f"Kein Knoten enthaelt '{begriff}'.", []
    return "Weitere KANDIDATEN aus der Suche:\n" + "\n".join(f"- {n}" for n in hits), hits


def _run_tool(graph, name: str, args: dict) -> tuple:
    """Fuehrt einen Werkzeugaufruf aus -> (Text fuers Modell, gesehene Knoten)."""
    if name != "suche_knoten":
        return f"Unbekanntes Werkzeug '{name}'.", []
    if "begriff" not in args:
        return "Fehlendes Argument 'begriff' fuer suche_knoten.", []
    return _tool_search(graph, str(args["begriff"]))


def judge(graph, term: str, candidates: list) -> dict:
    """
    Richter-Agent fuer einen Knoten -> {"treffer": Knotenname oder None,
    "begruendung": str, "schritte": ["suche_knoten(multiple sclerosis)", ...],
    "llm_aufrufe": n}. think=False wie beim Import-Richter: die Begruendung
    vor dem Treffer ersetzt den Denkschritt, und bei ~1.300 Knoten zaehlt
    jede Sekunde.
    """
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    messages = [{"role": "user", "content": template.format(
        term=term, candidates="\n".join(f"- {c}" for c in candidates),
    )}]
    seen, steps, calls = list(candidates), [], 0

    for _ in range(MAX_TOOL_ROUNDS):
        response = ollama.chat(model=JUDGE_MODEL, messages=messages, tools=TOOLS, think=False,
                               options={"num_predict": 400, "temperature": 0})
        calls += 1
        message = response["message"]
        tool_calls = message.get("tool_calls") or []
        final = next((c for c in tool_calls if c["function"]["name"] == "urteil"), None)
        if final:
            args = final["function"]["arguments"] or {}
            return _verdict(args.get("treffer"), args.get("begruendung"), term, seen, steps, calls)
        messages.append(message)
        if not tool_calls:
            break  # Klartext statt Werkzeug: Urteil unten per JSON nachfordern
        for call in tool_calls:
            name, args = call["function"]["name"], dict(call["function"]["arguments"] or {})
            text, nodes = _run_tool(graph, name, args)
            seen.extend(nodes)
            steps.append(f"{name}({', '.join(str(v) for v in args.values())})")
            messages.append({"role": "tool", "tool_name": name, "content": text})

    allowed = tuple(n for n in dict.fromkeys(seen) if n != term)
    messages.append({"role": "user", "content": FORCE_VERDICT})
    response = ollama.chat(model=JUDGE_MODEL, messages=messages, think=False, format=judge_schema(allowed),
                           options={"num_predict": 300, "temperature": 0})
    calls += 1
    # Abgeschnittene/kaputte Antwort = im Zweifel nicht zusammenfuehren (wie normalize.judge_verdict)
    try:
        verdict = json.loads(response["message"]["content"])
        answer, reason = verdict.get("treffer"), verdict.get("begruendung")
    except (json.JSONDecodeError, AttributeError, TypeError):
        answer, reason = None, "Antwort nicht lesbar"
    return _verdict(answer, reason, term, seen, steps, calls)


def _verdict(answer, reason, term: str, seen: list, steps: list, calls: int) -> dict:
    """Treffer nur, wenn der Agent den Knoten gesehen hat - nie ein erfundener Name, nie der Knoten selbst."""
    known = {str(n).casefold().strip(): n for n in seen if n != term}
    match = known.get(str(answer).casefold().strip()) if answer else None
    return {"treffer": match, "begruendung": reason or "", "schritte": steps, "llm_aufrufe": calls}


def _singular(word: str) -> str:
    # auf beide Namen gleich angewendet, daher reicht eine grobe Regel: "infections" -> "infection"
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _is_abbreviation_word(word: str) -> bool:
    return sum(c.isupper() for c in word) >= 2


def _short(word: str) -> str:
    """Abkuerzung ohne kleines Mehrzahl-s: "OPCs" -> "OPC"; "AIDS" und "CNS" bleiben."""
    return word[:-1] if word.endswith("s") and len(word) > 2 else word


def _tokens(text: str) -> tuple:
    """Woerter fuer den Vergleich: klein, ohne Mehrzahl, Bindestriche trennen, griechische Buchstaben ausgeschrieben."""
    for letter, word in GREEK.items():
        text = text.replace(letter, f" {word} ")
    return tuple(_short(w).casefold() if _is_abbreviation_word(w) else _singular(w.casefold())
                 for w in re.findall(WORD, text))


def _abbreviations(text: str) -> dict:
    """Abkuerzungen im Namen -> Buchstabengruppen: "IgE" -> ("ig", "e"), "OPCs" -> ("o", "p", "c")."""
    return {_short(w).casefold(): tuple(g.casefold() for g in re.findall(r"[^\W_][a-z]*", _short(w)))
            for w in re.findall(WORD, text) if _is_abbreviation_word(w)}


def _parts(name: str) -> tuple:
    """(Woerter, Woerter einer Klammer am Ende): "myelin water fraction (MWF)" -> (myelin, water, fraction), (mwf,)."""
    end = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", name)
    if end:
        return _tokens(end.group(1)), _tokens(end.group(2))
    return _tokens(re.sub(r"\([^)]*\)", " ", name)), ()


def _subsequence(letters: str, word: str) -> bool:
    rest = iter(word)
    return all(c in rest for c in letters)


def _spells(groups: tuple, words: tuple, abbreviations: frozenset, inner: int = 0) -> bool:
    """
    Ergeben die Woerter der Langform die Buchstabengruppen der Abkuerzung?
    Jedes Wort traegt seinen Anfangsbuchstaben bei, Kleinbuchstaben der
    Abkuerzung stammen aus demselben Wort ("IgE" = ImmunoGlobulin E, nicht
    Inflammatory Gene Expression). Fuellwoerter duerfen fehlen, tragen aber
    nichts bei. Eine Abkuerzung in der Langform zaehlt nur ganz ("RRMS" =
    Relapsing-Remitting MS, aber "MS symptoms" ist keine Langform von "MS").
    inner: so viele Grossbuchstaben duerfen aus dem Wortinneren kommen.
    """
    if not words:
        return not groups
    word, rest = words[0], words[1:]
    if word in abbreviations:
        return "".join(groups[:len(word)]) == word and _spells(groups[len(word):], rest, abbreviations, inner)
    if word in STOPWORDS:  # sonst waere ATP = Acceptance of The Pathology
        return _spells(groups, rest, abbreviations, inner)
    if groups and word[0] == groups[0][0] and _subsequence(groups[0][1:], word[1:]):
        if _spells(groups[1:], rest, abbreviations, inner):
            return True
        if inner and len(groups) > 1 and _subsequence(groups[0][1:] + groups[1], word[1:]) \
                and _spells(groups[2:], rest, abbreviations, inner - 1):
            return True
    return False


def _aligned(a: tuple, b: tuple, groups_a: dict, abbreviations_b: frozenset) -> bool:
    """Passen die Woerter von a der Reihe nach auf die von b - gleich, oder eine Abkuerzung aus a auf mehrere Woerter von b?"""
    if not a or not b:
        return not a and not b
    if a[0] == b[0] and _aligned(a[1:], b[1:], groups_a, abbreviations_b):
        return True
    groups = groups_a.get(a[0])
    return bool(groups) and any(_spells(groups, b[:k], abbreviations_b) and _aligned(a[1:], b[k:], groups_a, abbreviations_b)
                                for k in range(1, len(b) + 1))


def _defines(name: str, short: tuple) -> bool:
    """Nennt name die Abkuerzung short in einer Klammer am Ende, passend zu den Woertern davor ("docosahexaenoic acid (DHA)")?"""
    outer, inner = _parts(name)
    abbreviations = _abbreviations(name)
    groups = abbreviations.get(short[0]) if len(short) == 1 else None
    # die Klammer ist ein ausdruecklicher Beleg: ein Grossbuchstabe darf aus dem Wortinneren kommen (DocosaHexaenoic)
    return bool(groups) and inner == short and _spells(groups, outer, frozenset(abbreviations) - {short[0]}, inner=1)


def evidence(a: str, b: str) -> Optional[str]:
    """
    Belegen die Namen, dass a und b dasselbe sind? Bedingung fuer die
    Freigabe - nur Daten aus dem Graphen, kein Allgemeinwissen.
    -> "schreibweise": gleiche Woerter bis auf Gross-/Kleinschreibung,
       Bindestriche, Mehrzahl, Klammerzusatz ("viral infections" / "viral infection")
    -> "abkuerzung": jeder Buchstabe der Abkuerzung ist ein Wortanfang der
       Langform ("MS" / "multiple sclerosis"), oder die Langform nennt sie in
       einer Klammer am Ende ("DHA" / "docosahexaenoic acid (DHA)")
    -> None: kein Beleg ("MBI" / "BMI", "stress" / "psychological stress",
       "MS" / "Masitinib", "CVD" / "cardiovascular disease": V ist kein Wortanfang)
    """
    (outer_a, _), (outer_b, _) = _parts(a), _parts(b)
    if not outer_a or not outer_b:
        return None
    if outer_a == outer_b or "".join(outer_a) == "".join(outer_b):
        return "schreibweise"
    if _defines(b, outer_a) or _defines(a, outer_b):
        return "abkuerzung"
    groups_a, groups_b = _abbreviations(a), _abbreviations(b)
    if _aligned(outer_a, outer_b, groups_a, frozenset(groups_b)) \
            or _aligned(outer_b, outer_a, groups_b, frozenset(groups_a)):
        return "abkuerzung"
    return None


def name_partners(names: list) -> dict:
    """
    Knoten, deren Namen sich gegenseitig belegen (evidence) - Schreibvarianten
    und Abkuerzung/Langform, ohne Embedding und ohne Sprachmodell. Sie kommen
    zusaetzlich auf die Kandidatenliste: das Embedding stellt "multiple
    sclerosis" nicht neben "MS", und der Agent liess eigene Suchtreffer liegen.
    """
    partners, by_spelling, by_initial = defaultdict(set), defaultdict(list), defaultdict(list)
    for name in names:
        outer = _parts(name)[0]
        if outer:
            by_spelling["".join(outer)].append(name)
            by_initial[outer[0][0]].append(name)
    for group in by_spelling.values():
        for name in group:
            partners[name].update(n for n in group if n != name)
    for short in names:
        outer = _parts(short)[0]
        if not outer or len(outer) > 3 or not _abbreviations(short):
            continue
        for name in by_initial[outer[0][0]]:  # eine Langform beginnt mit dem ersten Buchstaben der Abkuerzung
            if name != short and evidence(short, name) == "abkuerzung":
                partners[short].add(name)
                partners[name].add(short)
    return partners


def _neighbors(graph, name: str) -> set:
    return set(graph.predecessors(name)) | set(graph.successors(name))


def _rivals(graph, term: str, match: str, partners: dict) -> list:
    """
    Passt die Abkuerzung auf mehrere Langformen ("MS": multiple sclerosis,
    myelin status, muscle strength), entscheiden die gemeinsamen Nachbarn im
    Graphen: die gewaehlte muss mehr davon haben als jede andere. -> die
    Langformen, die mindestens gleichauf liegen (leer = eindeutig).
    """
    short = min((term, match), key=lambda n: len(_parts(n)[0]))
    chosen = match if short == term else term
    longs = {"".join(_parts(p)[0]): p for p in partners.get(short, ()) if evidence(short, p) == "abkuerzung"}
    longs.pop("".join(_parts(chosen)[0]), None)
    shared = lambda name: len(_neighbors(graph, short) & _neighbors(graph, name) - {short, name})
    return sorted(p for p in longs.values() if shared(p) >= shared(chosen))


def find_duplicates(graph, threshold: float = DEDUPE_THRESHOLD, limit: Optional[int] = None,
                    progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """
    -> {"vorschlaege": [...], "richter_aufrufe": n, "llm_aufrufe": n, "knoten": N, "dauer_s": s}.
    richter_aufrufe zaehlt die Agenten-Laeufe (einer pro Knoten mit
    Kandidaten), llm_aufrufe die LLM-Aufrufe darin. limit begrenzt die
    Richter-Aufrufe (fuer Probelaeufe); progress(i, N) wird pro Knoten
    aufgerufen.
    """
    started = time.time()
    names = [str(n) for n in graph.nodes]
    if len(names) < 2:
        return {"vorschlaege": [], "richter_aufrufe": 0, "llm_aufrufe": 0, "knoten": len(names),
                "dauer_s": 0.0}
    matrix = embed_all(names)
    index = {name: i for i, name in enumerate(names)}
    partners = name_partners(names)

    compared, proposed, proposals, calls, llm_calls = set(), set(), [], 0, 0
    for i, name in enumerate(names):
        if progress:
            progress(i, len(names))
        if limit is not None and calls >= limit:
            break
        abbreviation = is_abbreviation(name)
        min_score = ABBREVIATION_THRESHOLD if abbreviation else threshold
        max_candidates = ABBREVIATION_MAX_CANDIDATES if abbreviation else MAX_CANDIDATES

        # zeilenweise statt N x N-Matrix: Speicher bleibt O(N) auch bei grossen Graphen
        scores = matrix @ matrix[i]
        scores[i] = -1.0
        order = np.argsort(-scores)[:max_candidates]
        candidates = [j for j in order if scores[j] >= min_score
                      and frozenset((i, j)) not in compared]
        candidates += [j for j in sorted(index[p] for p in partners.get(name, ()))
                       if j not in candidates and frozenset((i, j)) not in compared]
        if not candidates:
            continue
        compared.update(frozenset((i, j)) for j in candidates)

        calls += 1
        verdict = judge(graph, name, [names[j] for j in candidates])
        llm_calls += verdict["llm_aufrufe"]
        if verdict["treffer"] is None:
            continue
        # per suche_knoten kann der Treffer ausserhalb der Kandidaten liegen -
        # auch so ein Paar nur einmal pruefen und nur einmal vorschlagen
        j = index[verdict["treffer"]]
        compared.add(frozenset((i, j)))
        if frozenset((i, j)) in proposed:
            continue
        proposed.add(frozenset((i, j)))
        proposals.append(_proposal(graph, name, verdict, float(scores[j]), partners))

    proposals.sort(key=lambda p: -p["aehnlichkeit"])
    return {"vorschlaege": proposals, "richter_aufrufe": calls, "llm_aufrufe": llm_calls,
            "knoten": len(names), "dauer_s": round(time.time() - started, 1)}


def _proposal(graph, term: str, verdict: dict, score: float, partners: dict) -> dict:
    match = verdict["treffer"]
    degree = {n: graph.degree(n) for n in (term, match)}
    proof = evidence(term, match)
    if proof == "abkuerzung":
        # Antworten sind fuer Laien: die Langform bleibt ("Epstein-Barr virus" statt "EBV"), auch mit weniger Kanten
        keep, remove = sorted((term, match), key=lambda n: (len(_parts(n)[0]), degree[n]), reverse=True)
    else:
        keep, remove = (term, match) if degree[term] > degree[match] else (match, term)
    rivals = _rivals(graph, term, match, partners) if proof == "abkuerzung" else []
    if rivals:
        proof = None  # die Namen passen auf mehrere Langformen, und die Nachbarn entscheiden nicht
    return {
        "behalten": keep,
        "entfernen": remove,
        "begruendung": verdict["begruendung"],
        "schritte": verdict["schritte"],
        "beleg": proof,
        "mehrdeutig": rivals,
        "aehnlichkeit": round(score, 3),
        "kanten": {keep: degree[keep], remove: degree[remove]},
        "typen": {keep: graph.nodes[keep].get("type"), remove: graph.nodes[remove].get("type")},
        "freigegeben": proof is not None,
    }
