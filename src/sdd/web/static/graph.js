// Graph: Cytoscape over /api/graph with a label filter, search, side panel, expand and reset.
import { api } from "./api.js";
import { DEFAULT_LABELS, LABELS, css, h, labelColor } from "./dom.js";
import { PRESET_PREFIX, picker } from "./presets.js";

export function mount(el, arg) {
  let cy = null;
  const shown = new Set(DEFAULT_LABELS); // checked boxes
  const loaded = new Set(DEFAULT_LABELS); // labels the server was asked for
  let home = arg || "";

  const search = h("input", { type: "search", placeholder: "ID or title", "aria-label": "Search" });
  const filters = h("div", { class: "filters" });
  const side = h("aside", { class: "side" }, h("span", { class: "muted" }, "Click a node. Double-click expands its neighbours."));
  const canvas = h("div", { id: "cy" });
  const err = h("div", { class: "err" });
  const reset = h("button", { type: "button" }, "Reset");
  const presets = picker((name) => loadPreset(name));
  el.append(
    h("div", { class: "bar" }, h("h2", {}, "Graph"), search, reset, presets.el, h("span", { class: "grow" })),
    h("div", { class: "bar" }, filters),
    err,
    h("div", { class: "split" }, canvas, side),
  );

  for (const label of LABELS) {
    const box = h("input", { type: "checkbox", checked: DEFAULT_LABELS.includes(label), "aria-label": label });
    box.addEventListener("change", () => {
      if (box.checked) shown.add(label);
      else shown.delete(label);
      if (box.checked && !loaded.has(label)) {
        loaded.add(label); // never fetched (Agent): ask the server again
        load(home);
      } else applyFilter();
    });
    filters.append(h("label", {}, box, h("span", { class: "swatch", "data-label": label }), label));
  }

  function paintSwatches() {
    for (const s of filters.querySelectorAll(".swatch")) s.style.background = labelColor(s.dataset.label);
  }

  function style() {
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
    ];
  }

  function applyFilter() {
    if (!cy) return;
    cy.nodes().forEach((n) => {
      const known = LABELS.includes(n.data("label"));
      n.toggleClass("hidden", known && !shown.has(n.data("label")));
    });
  }

  function add(data) {
    const nodes = data.nodes.map((n) => ({
      group: "nodes",
      data: { id: n.id, label: n.label, title: n.title, short: n.id },
    }));
    const seen = new Set();
    const edges = [];
    for (const e of data.edges) {
      const id = `${e.source}|${e.type}|${e.target}`;
      if (seen.has(id)) continue;
      seen.add(id);
      edges.push({ group: "edges", data: { id, source: e.source, target: e.target, type: e.type } });
    }
    const have = new Set(cy.nodes().map((n) => n.id()));
    cy.add(nodes.filter((n) => !have.has(n.data.id)));
    const ids = new Set(cy.nodes().map((n) => n.id()));
    cy.add(
      edges.filter((e) => cy.getElementById(e.data.id).empty() && ids.has(e.data.source) && ids.has(e.data.target)),
    );
    applyFilter();
    cy.layout({ name: "cose", animate: false, fit: true, padding: 24 }).run();
  }

  async function showNode(id) {
    try {
      const n = await api.node(id);
      const rows = [h("h3", {}, n.id), h("div", { class: "muted small" }, n.label)];
      const dl = h("dl");
      for (const [k, v] of Object.entries(n.props)) {
        if (k === "content_hash" || k === "text") continue;
        dl.append(h("dt", {}, k), h("dd", {}, typeof v === "object" ? JSON.stringify(v) : String(v)));
      }
      rows.push(dl);
      for (const [type, list] of Object.entries(n.relationships || {})) {
        dl.append(
          h("dt", {}, type),
          ...list.map((r) =>
            h("dd", {}, h("a", { href: `#graph/${encodeURIComponent(r.id)}` }, `${r.direction === "in" ? "← " : "→ "}${r.id}`)),
          ),
        );
      }
      side.replaceChildren(...rows);
    } catch (e) {
      side.replaceChildren(h("div", { class: "err" }, e.message));
    }
  }

  async function loadPreset(name) {
    err.textContent = "";
    try {
      const data = await api.preset(name);
      cy.elements().remove();
      add(data);
      side.replaceChildren(h("h3", {}, name), h("span", { class: "muted small" }, `${data.nodes.length} nodes, ${data.edges.length} edges`));
      history.replaceState(null, "", `#graph/${encodeURIComponent(PRESET_PREFIX + name)}`);
    } catch (e) {
      err.textContent = e.message;
    }
  }

  async function load(focus) {
    err.textContent = "";
    if (focus.startsWith(PRESET_PREFIX)) return loadPreset(focus.slice(PRESET_PREFIX.length));
    try {
      if (!focus) {
        const b = await api.board();
        focus = b.milestone ? b.milestone.id : "";
      }
      home = focus;
      cy.elements().remove();
      add(await api.graph({ labels: [...loaded], focus: focus || undefined, depth: 1, limit: 300 }));
      if (focus) {
        const n = cy.getElementById(focus);
        if (n.nonempty()) {
          n.select();
          showNode(focus);
        }
      }
    } catch (e) {
      err.textContent = e.message;
    }
  }

  function init() {
    cy = cytoscape({ container: canvas, elements: [], style: style() });
    cy.on("tap", "node", (e) => {
      const id = e.target.id();
      showNode(id);
      history.replaceState(null, "", `#graph/${encodeURIComponent(id)}`); // keep the selection in the URL
    });
    cy.on("dbltap", "node", async (e) => {
      try {
        add(await api.graph({ labels: [...loaded], focus: e.target.id(), depth: 1, limit: 300 }));
      } catch (x) {
        err.textContent = x.message;
      }
    });
    paintSwatches();
    load(home);
  }

  reset.addEventListener("click", () => {
    search.value = "";
    for (const set of [shown, loaded]) {
      set.clear();
      DEFAULT_LABELS.forEach((l) => set.add(l));
    }
    for (const b of filters.querySelectorAll("input")) b.checked = DEFAULT_LABELS.includes(b.getAttribute("aria-label"));
    load("");
  });

  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    cy.nodes().removeClass("hit");
    if (!q) return;
    const hits = cy.nodes().filter((n) => n.id().toLowerCase().includes(q) || String(n.data("title")).toLowerCase().includes(q));
    hits.addClass("hit");
    if (hits.nonempty()) cy.animate({ fit: { eles: hits, padding: 60 }, duration: 200 });
  });
  search.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const q = search.value.trim();
    if (!q || cy.nodes(".hit").nonempty()) return;
    try {
      add(await api.graph({ labels: [...loaded], focus: q, depth: 1, limit: 300 })); // an exact ID not on screen yet
      showNode(q);
    } catch (x) {
      err.textContent = x.message;
    }
  });

  const onTheme = () => {
    paintSwatches();
    if (cy) cy.style(style());
  };
  window.addEventListener("themechange", onTheme);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", onTheme);
  init();

  return () => {
    window.removeEventListener("themechange", onTheme);
    matchMedia("(prefers-color-scheme: dark)").removeEventListener("change", onTheme);
    if (cy) cy.destroy();
  };
}
