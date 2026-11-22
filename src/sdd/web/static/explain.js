// Explain: a searchable file tree, the summary paragraph, and the chain feature -> spec -> tasks and
// commits -> deviations as a left-to-right layered graph.
import { api } from "./api.js";
import { ZOOM, cyStyle, elementsOf, smoothZoom } from "./cystyle.js";
import { h } from "./dom.js";

// Column of each label, left to right.
const LAYER = {
  File: 0,
  Feature: 1,
  Domain: 1,
  Table: 1,
  Spec: 2,
  Section: 2,
  AcceptanceCheck: 2,
  Task: 3,
  Milestone: 4,
  Commit: 4,
  Deviation: 5,
};
const GAP_X = 170;
const GAP_Y = 46;

function treeOf(paths) {
  const root = { dirs: new Map(), files: [] };
  for (const p of paths) {
    const parts = p.split("/");
    let node = root;
    for (const d of parts.slice(0, -1)) {
      if (!node.dirs.has(d)) node.dirs.set(d, { dirs: new Map(), files: [] });
      node = node.dirs.get(d);
    }
    node.files.push(p);
  }
  return root;
}

export function mount(el, arg) {
  let cy = null;
  let current = arg ? arg.replace(/^file:/, "") : "";

  const search = h("input", { type: "search", placeholder: "Filter files", "aria-label": "Filter files" });
  const tree = h("nav", { class: "tree", "aria-label": "Files" }, h("span", { class: "muted small" }, "Loading files…"));
  const summary = h("p", { class: "summary" }, "Pick a file to see why it exists.");
  const err = h("div", { class: "err" });
  const choices = h("div", { class: "choices" });
  const canvas = h("div", { id: "cy" });
  el.append(
    h("div", { class: "bar" }, h("h2", {}, "Explain")),
    h(
      "div",
      { class: "split explain" },
      h("aside", { class: "side filepick" }, search, tree),
      h("div", {}, summary, err, choices, canvas),
    ),
  );

  function renderTree(paths, open) {
    const build = (node, prefix) => {
      const out = [];
      for (const [name, sub] of [...node.dirs].sort((a, b) => a[0].localeCompare(b[0]))) {
        const det = h("details", { open: open || current.startsWith(`${prefix}${name}/`) }, h("summary", {}, name));
        det.append(...build(sub, `${prefix}${name}/`));
        out.push(det);
      }
      for (const p of node.files.sort()) {
        const a = h("a", { href: `#explain/${encodeURIComponent(p)}`, class: p === current ? "on" : "" }, p.split("/").pop());
        a.title = p;
        out.push(a);
      }
      return out;
    };
    tree.replaceChildren(...(paths.length ? build(treeOf(paths), "") : [h("span", { class: "muted small" }, "No files match.")]));
  }

  let all = [];
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    renderTree(q ? all.filter((p) => p.toLowerCase().includes(q)) : all, Boolean(q));
  });

  // Left-to-right layers by label; rows are centred in each column.
  function layout(nodes) {
    const cols = new Map();
    for (const n of nodes) {
      const c = LAYER[n.data("label")] ?? 3;
      if (!cols.has(c)) cols.set(c, []);
      cols.get(c).push(n);
    }
    const pos = {};
    const present = [...cols.keys()].sort((a, b) => a - b); // empty layers take no room
    for (const [c, list] of cols) {
      list.sort((a, b) => a.id().localeCompare(b.id()));
      list.forEach((n, i) => {
        pos[n.id()] = { x: present.indexOf(c) * GAP_X, y: (i - (list.length - 1) / 2) * GAP_Y };
      });
    }
    return pos;
  }

  async function run(path) {
    err.textContent = "";
    choices.replaceChildren();
    if (!path) return;
    try {
      const res = await api.explain(path);
      current = res.file.path;
      summary.textContent = res.summary;
      history.replaceState(null, "", `#explain/${encodeURIComponent(current)}`);
      for (const a of tree.querySelectorAll("a")) a.classList.toggle("on", a.title === current);
      let graph;
      try {
        graph = await api.preset(`explain:${current}`);
      } catch {
        graph = { nodes: [], edges: [] };
      }
      if (cy) cy.destroy();
      cy = cytoscape({ container: canvas, elements: elementsOf(graph), style: cyStyle(), ...ZOOM });
      smoothZoom(cy);
      cy.getElementById(res.file.id).addClass("target");
      const pos = layout(cy.nodes());
      cy.layout({ name: "preset", positions: (n) => pos[n.id()], fit: true, padding: 24, animate: false }).run();
    } catch (e) {
      if (cy) cy.destroy();
      cy = null;
      summary.textContent = "";
      if (e.code === "ambiguous_target") {
        choices.append(h("div", {}, `"${path}" matches more than one file. Pick one:`));
        for (const c of e.details.candidates || []) {
          const p = c.replace(/^file:/, "");
          choices.append(h("a", { class: "choice", href: `#explain/${encodeURIComponent(p)}` }, p));
        }
      } else err.textContent = e.message;
    }
  }

  api
    .targets()
    .then((t) => {
      all = t.filter((n) => n.label === "File").map((n) => n.id.replace(/^file:/, ""));
      renderTree(all, false);
    })
    .catch((e) => {
      tree.textContent = e.message;
    });

  const onTheme = () => {
    if (cy) cy.style(cyStyle());
  };
  window.addEventListener("themechange", onTheme);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", onTheme);
  run(current);

  return () => {
    window.removeEventListener("themechange", onTheme);
    matchMedia("(prefers-color-scheme: dark)").removeEventListener("change", onTheme);
    if (cy) cy.destroy();
  };
}
