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

  const nodes = new vis.DataSet(graphData.nodes.map(n => ({
    id: n.id, label: n.id, title: `${n.id}\nTyp: ${n.type}`,
    color: colors[n.type] || UNKNOWN_COLOR,
    borderWidth: highlightSet.has(n.id) ? 5 : 1,
    font: { size: 16 },
  })));
  const edges = new vis.DataSet(graphData.edges.map((e, i) => ({
    id: i, from: e.source, to: e.target, arrows: "to",
    label: edgeLabel(e), title: edgeTooltip(e),
    font: { size: 12, align: "horizontal", background: "rgba(255,255,255,0.85)" },
  })));

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

  const legend = document.getElementById("legend");
  legend.innerHTML = Object.entries(colors)
    .map(([t, c]) => `<div><span class="dot" style="background:${c}"></span>${t}</div>`).join("");
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
      return `<div>[${t.n}] ${t.subject} --${t.relation}--> ${t.object}${extra ? " | " + extra : ""}${origin}</div>`;
    }).join("");

  if (data.graph.nodes.length) renderGraph(data.graph, data.selected_nodes);
}

document.getElementById("askBtn").addEventListener("click", askQuestion);
document.getElementById("question").addEventListener("keydown", e => { if (e.key === "Enter") askQuestion(); });
document.getElementById("fullBtn").addEventListener("click", () => fullGraph ? renderGraph(fullGraph) : loadFullGraph());

loadFullGraph();
