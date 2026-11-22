// Cytoscape style shared by the Graph, Impact and Explain views (re-read on a theme change).
import { css, labelColor } from "./dom.js";

export function cyStyle() {
  return [
    {
      selector: "node",
      style: {
        "background-color": (n) => labelColor(n.data("label")),
        label: "data(short)",
        color: css("--fg-1"),
        "font-family": css("--font-mono"),
        "font-size": 9,
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
        "line-color": css("--fg-2"),
        opacity: 0.45,
        "target-arrow-color": css("--fg-2"),
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "arrow-scale": 0.7,
      },
    },
    { selector: "node:selected", style: { "border-width": 3, "border-color": css("--accent") } },
    { selector: ".hit", style: { "border-width": 3, "border-color": css("--warn") } },
    { selector: "node.dense", style: { width: 14, height: 14, "font-size": 8 } },
    { selector: "edge.dense", style: { "target-arrow-shape": "none", opacity: 0.5 } },
    { selector: "node.nolabel", style: { label: "" } },
    { selector: "node.nolabel:selected, node.nolabel.hover, node.nolabel.hit", style: { label: "data(short)" } },
    { selector: "node.dense:selected, node.dense.hover", style: { width: 20, height: 20 } },
    { selector: ".hidden", style: { display: "none" } },
    { selector: ".target", style: { width: 28, height: 28, "border-width": 3, "border-color": css("--accent") } },
    { selector: "node.dim", style: { opacity: 0.25 } },
    { selector: "edge.dim", style: { opacity: 0.12 } },
    { selector: "node.chain", style: { "border-width": 3, "border-color": css("--warn") } },
    { selector: "edge.chain", style: { width: 3, opacity: 1, "line-color": css("--warn"), "target-arrow-color": css("--warn") } },
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

// A dense graph: small nodes, no arrowheads, and a label only on the busiest nodes, on hover, on
// selection and on search hits. Call after the elements are added; `keep` is how many hubs stay labelled.
export function declutter(cy, limit = 120, keep = 12) {
  const dense = cy.nodes().length > limit;
  cy.nodes().toggleClass("dense", dense).toggleClass("nolabel", dense);
  cy.edges().toggleClass("dense", dense);
  if (dense) {
    cy.nodes().sort((a, b) => b.degree() - a.degree()).slice(0, keep).removeClass("nolabel");
    cy.off("mouseover mouseout", "node"); // set() can run again on the same cy
    cy.on("mouseover", "node", (e) => e.target.addClass("hover"));
    cy.on("mouseout", "node", (e) => e.target.removeClass("hover"));
  }
  return dense;
}

// Zoom feel shared by every Cytoscape view. Cytoscape's own wheel step depends on the device (a
// trackpad or a free-spinning wheel sends many large deltas), so the wheel is handled here: one
// clamped exponential step per event, the same everywhere, centred on the pointer. Pinch still goes
// through Cytoscape. `ZOOM` goes into the cytoscape() options.
export const ZOOM = { minZoom: 0.04, maxZoom: 3 };

export function smoothZoom(cy) {
  const el = cy.container();
  // on the parent, in the capture phase: Cytoscape's own wheel listener sits on the container itself
  // and was registered first, so a listener on the container would run after it
  const guard = el.parentElement || el;
  const onWheel = (e) => {
    if (!el.contains(e.target)) return;
    e.preventDefault();
    e.stopImmediatePropagation(); // Cytoscape never sees the wheel
    const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 100 : e.deltaY;
    const step = Math.max(-100, Math.min(100, delta)) * 0.0012; // at most about 13% per event
    const level = Math.min(ZOOM.maxZoom, Math.max(ZOOM.minZoom, cy.zoom() * Math.exp(-step)));
    const box = el.getBoundingClientRect();
    cy.zoom({ level, renderedPosition: { x: e.clientX - box.left, y: e.clientY - box.top } });
  };
  guard.addEventListener("wheel", onWheel, { capture: true, passive: false });
  // the parent outlives cy (a view redraws into the same container): a stale listener would swallow
  // the new one's wheel
  cy.on("destroy", () => guard.removeEventListener("wheel", onWheel, { capture: true }));
}
