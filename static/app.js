const PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
                 "#b279a2", "#eeca3b", "#9d755d", "#ff9da6", "#79706e"];
const UNKNOWN_COLOR = "#bab0ac";

let network = null;
let fullGraph = null; // letzte GET /graph-Antwort, fuer den "Ganzer Graph"-Button

function typeColors(nodes) {
  const types = [...new Set(nodes.map(n => n.type).filter(Boolean))].sort();
  const colors = {};
  types.forEach((t, i) => colors[t] = PALETTE[i % PALETTE.length]);
  return colors;
}

function wrapLabel(text, width = 28) {
  const words = String(text).split(" ");
  const lines = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > width) { lines.push(line.trim()); line = w; }
    else { line += " " + w; }
  }
  if (line.trim()) lines.push(line.trim());
  return lines;
}

function edgeLabel(e) {
  const lines = [e.relation || ""];
  if (e.value != null) lines.push(...wrapLabel(e.value));
  if (e.condition != null) lines.push(...wrapLabel(`(${e.condition})`));
  return lines.join("\n");
}

function edgeTooltip(e) {
  const parts = [e.relation || ""];
  for (const [key, label] of [["value", "value"], ["condition", "condition"],
                               ["evidence_level", "evidence"], ["confidence", "confidence"],
                               ["origin", "Quelle"]]) {
    if (e[key] != null) parts.push(`${label}: ${e[key]}`);
  }
  return parts.join("\n");
}

function renderGraph(graphData, highlight = []) {
  const highlightSet = new Set(highlight);
  const colors = typeColors(graphData.nodes);
  const nodeById = new Map(graphData.nodes.map(n => [n.id, n]));

  // Bei einer Frage (highlight gesetzt): nur die direkten Kanten der
  // relevanten Knoten sofort zeigen, alles Weitere erst per Klick auf einen
  // gestrichelten Knoten aufdecken - sonst ist der Teilgraph bei groesseren
  // Fragen (viele 2-Hop-Kanten) sofort unuebersichtlich voll. Beim vollen
  // Graphen (kein highlight) bleibt alles sofort sichtbar wie bisher.
  const progressive = highlightSet.size > 0;

  const edgesByNode = new Map();
  graphData.edges.forEach((e, i) => {
    for (const n of [e.source, e.target]) {
      if (!edgesByNode.has(n)) edgesByNode.set(n, []);
      edgesByNode.get(n).push(i);
    }
  });

  const revealedEdges = new Set();
  const visibleNodes = new Set();
  if (progressive) {
    graphData.edges.forEach((e, i) => {
      if (highlightSet.has(e.source) || highlightSet.has(e.target)) {
        revealedEdges.add(i);
        visibleNodes.add(e.source);
        visibleNodes.add(e.target);
      }
    });
    highlightSet.forEach(n => visibleNodes.add(n)); // falls ganz ohne eigene Kante
  } else {
    graphData.edges.forEach((_, i) => revealedEdges.add(i));
    graphData.nodes.forEach(n => visibleNodes.add(n.id));
  }
  // Knoten aus der ersten Ansicht bleiben immer sichtbar (nur ihre extra
  // Kanten werden auf-/zugeklappt). Erst per Klick dazugekommene Knoten
  // koennen beim Zuklappen komplett wieder verschwinden.
  const rootNodes = new Set(visibleNodes);
  const expandedBy = new Map(); // Knoten-Id -> Liste der durch ihn aufgedeckten Kanten-Indizes

  function hiddenCount(nodeId) {
    return (edgesByNode.get(nodeId) || []).filter(i => !revealedEdges.has(i)).length;
  }

  function nodeVisual(n) {
    const extra = hiddenCount(n.id);
    return {
      id: n.id,
      label: extra > 0 ? `${n.id}  (+${extra})` : n.id,
      title: `${n.id}\nTyp: ${n.type}` + (extra > 0 ? `\nKlicken fuer ${extra} weitere Verbindung(en)` : ""),
      color: colors[n.type] || UNKNOWN_COLOR,
      borderWidth: highlightSet.has(n.id) ? 5 : 1,
      shapeProperties: { borderDashes: extra > 0 ? [5, 3] : false },
      font: { size: 16 },
    };
  }

  function edgeVisual(i) {
    const e = graphData.edges[i];
    return {
      id: i, from: e.source, to: e.target, arrows: "to",
      label: edgeLabel(e), title: edgeTooltip(e),
      font: { size: 12, align: "horizontal", background: "rgba(255,255,255,0.85)" },
    };
  }

  const nodes = new vis.DataSet([...visibleNodes].map(id => nodeVisual(nodeById.get(id))));
  const edges = new vis.DataSet([...revealedEdges].map(edgeVisual));

  const container = document.getElementById("graph");
  const options = {
    physics: {
      solver: "forceAtlas2Based",
      forceAtlas2Based: { gravitationalConstant: -80, centralGravity: 0.03, springLength: 190, springConstant: 0.06, avoidOverlap: 0.5 },
      stabilization: { iterations: 300, fit: true },
    },
    interaction: { hover: true, tooltipDelay: 100 },
  };
  if (network) network.destroy();
  network = new vis.Network(container, { nodes, edges }, options);
  // Physik bleibt nach der Stabilisierung sonst dauerhaft an und bei kleinen
  // Teilgraphen kann das System dann in einer stabilen Rotation haengen
  // bleiben, statt zu stoppen - deshalb hier abschalten, sobald stabil.
  network.once("stabilizationIterationsDone", () => network.setOptions({ physics: false }));

  function resettle() {
    network.setOptions({ physics: true });
    network.once("stabilizationIterationsDone", () => network.setOptions({ physics: false }));
  }

  function expandNode(clickedId) {
    const toReveal = (edgesByNode.get(clickedId) || []).filter(i => !revealedEdges.has(i));
    if (!toReveal.length) return;

    const newNodeIds = new Set();
    toReveal.forEach(i => {
      revealedEdges.add(i);
      edges.add(edgeVisual(i));
      const e = graphData.edges[i];
      for (const n of [e.source, e.target]) {
        if (!visibleNodes.has(n)) { visibleNodes.add(n); newNodeIds.add(n); }
      }
    });
    newNodeIds.forEach(id => nodes.add(nodeVisual(nodeById.get(id))));
    expandedBy.set(clickedId, toReveal);
    // Betroffene Knoten neu zeichnen, da sich ihre "versteckte Kanten"-Anzahl aendert.
    new Set([clickedId, ...newNodeIds]).forEach(id => nodes.update(nodeVisual(nodeById.get(id))));
    resettle();
  }

  function maybeRemoveNode(nodeId) {
    if (rootNodes.has(nodeId)) { nodes.update(nodeVisual(nodeById.get(nodeId))); return; }
    const stillVisible = (edgesByNode.get(nodeId) || []).some(i => revealedEdges.has(i));
    if (stillVisible) {
      // Bleibt sichtbar, aber die Anzahl seiner versteckten Kanten kann sich
      // geaendert haben (z.B. eine Kante, die durch den Elternknoten gezeigt
      // wurde, ist jetzt wieder versteckt) - Label/Rahmen neu berechnen.
      nodes.update(nodeVisual(nodeById.get(nodeId)));
      return;
    }
    // Hatte dieser Knoten selbst etwas aufgedeckt: das zuerst rekursiv einklappen.
    if (expandedBy.has(nodeId)) collapseNode(nodeId, { resettleAfter: false });
    visibleNodes.delete(nodeId);
    nodes.remove(nodeId);
  }

  function collapseNode(clickedId, { resettleAfter = true } = {}) {
    const edgesToHide = expandedBy.get(clickedId);
    if (!edgesToHide) return;
    expandedBy.delete(clickedId);

    const touched = new Set();
    edgesToHide.forEach(i => {
      revealedEdges.delete(i);
      edges.remove(i);
      const e = graphData.edges[i];
      touched.add(e.source);
      touched.add(e.target);
    });
    touched.delete(clickedId);
    touched.forEach(maybeRemoveNode);

    if (nodes.get(clickedId)) nodes.update(nodeVisual(nodeById.get(clickedId)));
    if (resettleAfter) resettle();
  }

  if (progressive) {
    network.on("click", params => {
      if (!params.nodes.length) return;
      const clickedId = params.nodes[0];
      if (expandedBy.has(clickedId)) collapseNode(clickedId);
      else expandNode(clickedId);
    });
  }

  const legend = document.getElementById("legend");
  legend.innerHTML = Object.entries(colors)
    .map(([t, c]) => `<div><span class="dot" style="background:${c}"></span>${t}</div>`).join("")
    + (progressive ? '<div style="margin-top:6px;color:#888">Gestrichelte Knoten: anklicken zum Auf-/Zuklappen</div>' : "");
}

async function loadFullGraph() {
  const res = await fetch("/graph");
  fullGraph = await res.json();
  document.getElementById("status").textContent = `${fullGraph.nodes.length} Knoten, ${fullGraph.edges.length} Kanten`;
  document.getElementById("answer").textContent = "";
  document.getElementById("belege").innerHTML = "";
  renderGraph(fullGraph);
}

async function askQuestion() {
  const question = document.getElementById("question").value.trim();
  if (!question) return;

  document.getElementById("status").textContent = "Frage laeuft...";
  document.getElementById("answer").textContent = "";
  document.getElementById("belege").innerHTML = "";

  const res = await fetch("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const data = await res.json();

  document.getElementById("status").textContent = data.selected_nodes.length
    ? `Relevante Knoten: ${data.selected_nodes.join(", ")}` : "";
  document.getElementById("answer").textContent = data.answer;
  document.getElementById("belege").innerHTML = data.triples
    .map(t => {
      const extra = [["value", t.value], ["condition", t.condition],
                      ["evidence", t.evidence_level], ["confidence", t.confidence]]
        .filter(([, v]) => v != null).map(([label, v]) => `${label}: ${v}`).join(" | ");
      const origin = t.origin ? `<div class="origin">Quelle: ${t.origin}</div>` : "";
      // Niedrige confidence graut aus, hohe wird fett - macht auf einen
      // Blick sichtbar, wie gut ein Beleg abgesichert ist, ohne die Zahl
      // lesen zu muessen.
      const confClass = t.confidence == null ? "" : t.confidence >= 0.9 ? "conf-high" : t.confidence < 0.7 ? "conf-low" : "";
      return `<div><span class="${confClass}">[${t.n}] ${t.subject} --${t.relation}--> ${t.object}${extra ? " | " + extra : ""}</span>${origin}</div>`;
    }).join("");

  if (data.graph.nodes.length) renderGraph(data.graph, data.selected_nodes);
}

document.getElementById("askBtn").addEventListener("click", askQuestion);
document.getElementById("question").addEventListener("keydown", e => { if (e.key === "Enter") askQuestion(); });
document.getElementById("fullBtn").addEventListener("click", () => fullGraph ? renderGraph(fullGraph) : loadFullGraph());

loadFullGraph();
