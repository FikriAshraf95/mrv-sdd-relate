// Cytoscape style shared by the Graph, Impact and Explain views (re-read on a theme change).
import { css, labelColor } from "./dom.js";

export function cyStyle() {
  return [
    {
      selector: "node",
      style: {
        "background-color": (n) => labelColor(n.data("label")),
        label: "data(short)",
        color: css("--text"),
        "font-size": 10,
        "text-valign": "bottom",
        "text-margin-y": 3,
        "text-wrap": "ellipsis",
        "text-max-width": 90,
        width: 18,
        height: 18,
      },
    },
    {
      selector: "edge",
      style: {
        width: 1,
        "line-color": css("--line"),
        "target-arrow-color": css("--muted"),
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "arrow-scale": 0.7,
      },
    },
    { selector: "node:selected", style: { "border-width": 3, "border-color": css("--accent") } },
    { selector: ".hit", style: { "border-width": 3, "border-color": css("--warn") } },
    { selector: ".hidden", style: { display: "none" } },
    { selector: ".target", style: { width: 28, height: 28, "border-width": 3, "border-color": css("--accent") } },
    { selector: "node.dim", style: { opacity: 0.25 } },
    { selector: "edge.dim", style: { opacity: 0.12 } },
    { selector: "node.chain", style: { "border-width": 3, "border-color": css("--warn") } },
    { selector: "edge.chain", style: { width: 3, "line-color": css("--warn"), "target-arrow-color": css("--warn") } },
  ];
}

// Graph payload ({nodes, edges}) -> Cytoscape elements; edges deduplicated, dangling ones dropped.
export function elementsOf(data) {
  const ids = new Set(data.nodes.map((n) => n.id));
  const seen = new Set();
  const edges = [];
  for (const e of data.edges) {
    const id = `${e.source}|${e.type}|${e.target}`;
    if (seen.has(id) || !ids.has(e.source) || !ids.has(e.target)) continue;
    seen.add(id);
    edges.push({ group: "edges", data: { id, source: e.source, target: e.target, type: e.type } });
  }
  const nodes = data.nodes.map((n) => ({
    group: "nodes",
    data: { id: n.id, label: n.label, title: n.title, short: n.id },
  }));
  return [...nodes, ...edges];
}

// A `via` chain (SPEC-06 §2) -> the node IDs and the edge IDs it walks. `[a, "<-T", b]` is `b -T-> a`.
export function chainOf(via, itemId) {
  const nodes = via.filter((_, i) => i % 2 === 0);
  if (itemId && nodes[nodes.length - 1] !== itemId) nodes.push(itemId);
  const edges = [];
  for (let i = 0; i + 2 < via.length; i += 2) {
    const [a, rel, b] = [via[i], via[i + 1], via[i + 2]];
    edges.push(rel.startsWith("<-") ? `${b}|${rel.slice(2)}|${a}` : `${a}|${rel.slice(2)}|${b}`);
  }
  return { nodes, edges };
}
