const PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
                 "#b279a2", "#eeca3b", "#9d755d", "#ff9da6", "#79706e"];
const UNKNOWN_COLOR = "#bab0ac";

let network = null;
let fullGraph = null; // letzte GET /graph-Antwort, fuer den "Ganzer Graph"-Button

// Welcher polygraph-service abgefragt wird: leer = der Server, der diese
// Seite ausliefert; sonst z.B. "http://localhost:8001" (Kollegen-Instanz).
// Wird im Browser gemerkt, damit ein Reload beim gewaehlten Service bleibt.
const SERVICE_KEY = "polygraph.serviceUrl";

function serviceBase() {
  return document.getElementById("serviceUrl").value.trim().replace(/\/+$/, "");
}

function rememberService() {
  try { localStorage.setItem(SERVICE_KEY, serviceBase()); } catch {}
}

// Daten koennen jetzt von einem fremden Service kommen - vor innerHTML escapen.
function esc(text) {
  return String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function fetchService(path, init) {
  const url = serviceBase() + path;
  let res;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error(`Service nicht erreichbar: ${serviceBase() || "dieser Server"}`);
  }
  if (!res.ok) throw new Error(`${url} antwortet mit ${res.status}`);
  return res.json();
}

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
    // Neue Knoten direkt neben dem angeklickten Knoten starten lassen, statt
    // alle uebereinander bei (0,0) - sonst schleudert die Abstossungskraft
    // sie beim naechsten Stabilisieren explosionsartig auseinander, und
    // dieser Ruck bringt den ganzen (auch laengst eingependelten) Graphen
    // ins Rotieren.
    const clickedPos = network.getPositions([clickedId])[clickedId] || { x: 0, y: 0 };
    newNodeIds.forEach(id => nodes.add({
      ...nodeVisual(nodeById.get(id)),
      x: clickedPos.x + (Math.random() - 0.5) * 60,
      y: clickedPos.y + (Math.random() - 0.5) * 60,
    }));
    expandedBy.set(clickedId, toReveal);
    // Betroffene Knoten neu zeichnen, da sich ihre "versteckte Kanten"-Anzahl aendert.
    new Set([clickedId, ...newNodeIds]).forEach(id => nodes.update(nodeVisual(nodeById.get(id))));

    // Nur die neu aufgedeckten Knoten von der Physik bewegen lassen - bereits
    // eingependelte Knoten bleiben fest, statt bei jedem Klick den ganzen
    // Graphen neu durcheinanderzuwirbeln.
    visibleNodes.forEach(id => {
      if (!newNodeIds.has(id)) nodes.update({ id, physics: false });
    });
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
    if (expandedBy.has(nodeId)) collapseNode(nodeId);
    visibleNodes.delete(nodeId);
    nodes.remove(nodeId);
  }

  function collapseNode(clickedId) {
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
    // Kein resettle() hier: beim Zuklappen kommt nichts Neues hinzu, die
    // verbleibenden Knoten sollen einfach an Ort und Stelle bleiben statt
    // dass die Physik-Simulation (mit ihrem Rotationsrisiko) erneut anspringt.
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
    .map(([t, c]) => `<div><span class="dot" style="background:${c}"></span>${esc(t)}</div>`).join("")
    + (progressive ? '<div style="margin-top:6px;color:#888">Gestrichelte Knoten: anklicken zum Auf-/Zuklappen</div>' : "");
}

async function loadFullGraph() {
  document.getElementById("answer").textContent = "";
  document.getElementById("belege").innerHTML = "";
  try {
    fullGraph = await fetchService("/graph");
  } catch (err) {
    fullGraph = null;
    document.getElementById("status").textContent = err.message;
    return;
  }
  document.getElementById("status").textContent = `${fullGraph.nodes.length} Knoten, ${fullGraph.edges.length} Kanten`;
  renderGraph(fullGraph);
}

async function askQuestion() {
  const question = document.getElementById("question").value.trim();
  if (!question) return;

  document.getElementById("status").textContent = "Frage laeuft...";
  document.getElementById("answer").textContent = "";
  document.getElementById("belege").innerHTML = "";

  let data;
  try {
    data = await fetchService("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  } catch (err) {
    document.getElementById("status").textContent = err.message;
    return;
  }

  document.getElementById("status").textContent = data.selected_nodes.length
    ? `Relevante Knoten: ${data.selected_nodes.join(", ")}` : "";
  document.getElementById("answer").textContent = data.answer;
  document.getElementById("belege").innerHTML = data.triples
    .map(t => {
      const extra = [["value", t.value], ["condition", t.condition],
                      ["evidence", t.evidence_level], ["confidence", t.confidence]]
        .filter(([, v]) => v != null).map(([label, v]) => `${label}: ${v}`).join(" | ");
      const origin = t.origin ? `<div class="origin">Quelle: ${esc(t.origin)}</div>` : "";
      // Niedrige confidence graut aus, hohe wird fett - macht auf einen
      // Blick sichtbar, wie gut ein Beleg abgesichert ist, ohne die Zahl
      // lesen zu muessen.
      const confClass = t.confidence == null ? "" : t.confidence >= 0.9 ? "conf-high" : t.confidence < 0.7 ? "conf-low" : "";
      return `<div><span class="${confClass}">[${t.n}] ${esc(`${t.subject} --${t.relation}--> ${t.object}${extra ? " | " + extra : ""}`)}</span>${origin}</div>`;
    }).join("");

  if (data.graph.nodes.length) renderGraph(data.graph, data.selected_nodes);
}

// Beispielfragen aus dem Graphen (GET /questions/suggest): jeder Klick auf
// "Fragen vorschlagen" holt neue; ein Klick auf einen Vorschlag stellt ihn.
async function suggestQuestions() {
  const box = document.getElementById("suggestions");
  const btn = document.getElementById("suggestBtn");
  box.innerHTML = "";
  btn.disabled = true;
  document.getElementById("status").textContent = "Fragen werden vorgeschlagen...";
  let data;
  try {
    data = await fetchService("/questions/suggest");
  } catch (err) {
    document.getElementById("status").textContent = err.message;
    return;
  } finally {
    btn.disabled = false;
  }
  document.getElementById("status").textContent = data.questions.length
    ? "" : "Der Graph ist leer - noch keine Vorschlaege moeglich.";
  for (const q of data.questions) {
    const b = document.createElement("button");
    b.textContent = q.question;  // textContent statt innerHTML: Daten koennen von fremden Services kommen
    b.addEventListener("click", () => {
      document.getElementById("question").value = q.question;
      askQuestion();
    });
    box.appendChild(b);
  }
}

document.getElementById("askBtn").addEventListener("click", askQuestion);
document.getElementById("suggestBtn").addEventListener("click", suggestQuestions);
document.getElementById("question").addEventListener("keydown", e => { if (e.key === "Enter") askQuestion(); });
document.getElementById("fullBtn").addEventListener("click", () => fullGraph ? renderGraph(fullGraph) : loadFullGraph());

document.getElementById("serviceBtn").addEventListener("click", () => { rememberService(); fullGraph = null; loadFullGraph(); });
document.getElementById("serviceUrl").addEventListener("keydown", e => {
  if (e.key === "Enter") { rememberService(); fullGraph = null; loadFullGraph(); }
});

try { document.getElementById("serviceUrl").value = localStorage.getItem(SERVICE_KEY) || ""; } catch {}
loadFullGraph();
