// Graph tab: the whole graph in 3D (graph3d.js, loaded on demand) or 2D (graph2d.js, Cytoscape),
// with a label filter, search, side panel, expand and reset. This module owns the data; the two
// views only draw it, so the 2D/3D toggle keeps the selection and the expanded neighbours.
// Hash: `#graph/3d`, `#graph/2d`, `#graph/<node id>`, `#graph/preset:<name>` (presets open in 2D).
import { api } from "./api.js";
import { DEFAULT_LABELS, LABELS, h, labelColor } from "./dom.js";
import { PRESET_PREFIX, picker } from "./presets.js";
import { failure, loading } from "./state.js";

const LIMIT = 2000; // the endpoint's cap
let lastMode = ""; // the mode this tab last showed, kept while the page lives

function webgl() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function mount(el, arg) {
  const canGL = webgl();
  const isPreset = (arg || "").startsWith(PRESET_PREFIX);
  let mode = canGL && lastMode !== "2d" ? "3d" : "2d";
  if (arg === "2d" || arg === "3d") mode = arg;
  if (isPreset) mode = "2d";
  if (!canGL) mode = "2d";
  let wanted = mode; // the mode last asked for; `mode` changes only when a build finishes
  let focus = arg && arg !== "2d" && arg !== "3d" && !isPreset ? arg : "";

  const shown = new Set(DEFAULT_LABELS);
  const loaded = new Set(DEFAULT_LABELS);
  const nodes = new Map();
  const edges = new Map();
  let view = null;
  let selected = "";
  let closed = false;
  let building = 0;

  const search = h("input", { type: "search", placeholder: "ID or title", "aria-label": "Search" });
  const filters = h("div", { class: "filters" });
  const side = h("aside", { class: "side" }, h("span", { class: "muted" }, "Click a node. Double-click expands its neighbours."));
  const stage = h("div", { class: "stage" }, loading());
  const note = h("div", { class: "stagebar" });
  const err = h("div", { class: "err" });
  const reset = h("button", { type: "button" }, "Reset");
  const b2 = h("button", { type: "button", "aria-pressed": "false" }, "2D");
  const b3 = h("button", { type: "button", "aria-pressed": "false", disabled: !canGL, title: canGL ? "" : "3D needs WebGL, which this browser does not offer" }, "3D");
  const presets = picker((name) => loadPreset(name));
  el.append(
    h("div", { class: "bar" }, h("h2", {}, "Graph"), h("span", { class: "seg", role: "group", "aria-label": "Dimensions" }, b2, b3), search, reset, presets.el),
    h("div", { class: "bar" }, filters),
    err,
    h("div", { class: "split" }, h("div", { class: "stage-wrap" }, stage), side),
  );

  for (const label of LABELS) {
    const box = h("input", { type: "checkbox", checked: DEFAULT_LABELS.includes(label), "aria-label": label });
    box.addEventListener("change", () => {
      if (box.checked) shown.add(label);
      else shown.delete(label);
      if (box.checked && !loaded.has(label)) {
        loaded.add(label); // never fetched (Agent): ask the server again
        load();
      } else {
        if (view) view.setShown(shown);
        counts();
      }
    });
    filters.append(h("label", {}, box, h("span", { class: "swatch", "data-label": label }), label));
  }

  function paintSwatches() {
    for (const s of filters.querySelectorAll(".swatch")) s.style.background = labelColor(s.dataset.label);
  }

  function counts(extra = "") {
    const n = [...nodes.values()].filter((x) => !LABELS.includes(x.label) || shown.has(x.label)).length;
    const cap = nodes.size >= LIMIT ? ` · first ${LIMIT} nodes, filter labels to see others` : "";
    const hint = mode === "3d" ? " · drag to orbit, scroll to zoom" : "";
    note.textContent = `${n} nodes · ${edges.size} edges${cap}${extra}${hint}`;
  }

  function merge(data) {
    for (const n of data.nodes) if (!nodes.has(n.id)) nodes.set(n.id, n);
    for (const e of data.edges) edges.set(`${e.source}|${e.type}|${e.target}`, e);
  }

  function draw() {
    if (!view) return;
    view.set([...nodes.values()], [...edges.values()]);
    view.setShown(shown);
    if (selected) view.select(selected);
    counts();
  }

  async function build(next) {
    const mine = ++building;
    if (view) view.destroy();
    view = null;
    const host = h("div", { class: "host" });
    stage.replaceChildren(host, note);
    let made = null;
    if (next === "3d") {
      try {
        made = (await import("./graph3d.js")).create(host, hooks);
      } catch (x) {
        next = wanted = "2d";
        err.textContent = `3D view unavailable (${x.message}); showing 2D.`;
        b3.disabled = true;
      }
    }
    if (mine !== building || closed) {
      if (made) made.destroy();
      return;
    }
    if (!made) made = (await import("./graph2d.js")).create(host, hooks);
    if (mine !== building || closed) return made.destroy();
    view = made;
    mode = next;
    lastMode = next;
    b2.setAttribute("aria-pressed", String(next === "2d"));
    b3.setAttribute("aria-pressed", String(next === "3d"));
    draw();
  }

  const hooks = {
    onSelect(id) {
      selected = id;
      showNode(id);
      history.replaceState(null, "", `#graph/${encodeURIComponent(id)}`);
    },
    async onExpand(id) {
      try {
        const more = await api.graph({ labels: [...loaded], focus: id, depth: 1, limit: 300 });
        if (closed || !view) return;
        merge(more);
        draw();
      } catch (x) {
        if (!closed) err.textContent = x.message;
      }
    },
  };

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
      if (closed) return;
      nodes.clear();
      edges.clear();
      merge(data);
      selected = "";
      wanted = "2d";
      if (mode !== "2d" || !view) await build("2d");
      else draw();
      if (closed) return;
      side.replaceChildren(h("h3", {}, name), h("span", { class: "muted small" }, `${data.nodes.length} nodes, ${data.edges.length} edges`));
      history.replaceState(null, "", `#graph/${encodeURIComponent(PRESET_PREFIX + name)}`);
    } catch (e) {
      if (!closed) err.textContent = e.message;
    }
  }

  // the whole graph (up to the cap); a deep-linked node outside it is fetched with its neighbours
  async function load() {
    err.textContent = "";
    try {
      const all = await api.graph({ labels: [...loaded], limit: LIMIT });
      if (closed) return;
      nodes.clear();
      edges.clear();
      merge(all);
      if (focus && !nodes.has(focus)) {
        try {
          merge(await api.graph({ labels: [...loaded], focus, depth: 1, limit: 300 }));
        } catch (x) {
          err.textContent = x.message; // a stale deep link: still show the whole graph
          focus = "";
        }
        if (closed) return;
      }
      if (focus && nodes.has(focus)) {
        selected = focus;
        showNode(focus);
      }
      if (!view) await build(mode);
      else draw();
      if (selected && view) view.search(selected); // fly to the deep-linked node
    } catch (e) {
      if (closed) return;
      // keep a drawn graph on screen and report in the error line; only an empty stage shows the state
      if (view) err.textContent = e.message;
      else stage.replaceChildren(failure(e.message));
    }
  }

  const setMode = (next) => {
    if (next === wanted || (next === "3d" && !canGL)) return;
    wanted = next;
    history.replaceState(null, "", `#graph/${next}`);
    build(next);
  };
  b2.addEventListener("click", () => setMode("2d"));
  b3.addEventListener("click", () => setMode("3d"));

  reset.addEventListener("click", () => {
    search.value = "";
    selected = "";
    focus = "";
    for (const set of [shown, loaded]) {
      set.clear();
      DEFAULT_LABELS.forEach((l) => set.add(l));
    }
    for (const b of filters.querySelectorAll("input")) b.checked = DEFAULT_LABELS.includes(b.getAttribute("aria-label"));
    history.replaceState(null, "", `#graph/${mode}`);
    side.replaceChildren(h("span", { class: "muted" }, "Click a node. Double-click expands its neighbours."));
    load().then(() => view && view.reset());
  });

  search.addEventListener("input", () => view && view.search(search.value));
  search.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || !view) return;
    const q = search.value.trim();
    if (!q || view.search(q)) return;
    try {
      const more = await api.graph({ labels: [...loaded], focus: q, depth: 1, limit: 300 }); // an exact ID not on screen yet
      if (closed || !view) return;
      merge(more);
      selected = q;
      draw();
      view.search(q);
      showNode(q);
    } catch (x) {
      err.textContent = x.message;
    }
  });

  const onTheme = () => {
    paintSwatches();
    if (view) view.restyle();
  };
  window.addEventListener("themechange", onTheme);
  paintSwatches();
  if (isPreset) {
    build("2d").then(() => loadPreset(arg.slice(PRESET_PREFIX.length)));
  } else load();

  return () => {
    closed = true;
    window.removeEventListener("themechange", onTheme);
    if (view) view.destroy();
    view = null;
  };
}
