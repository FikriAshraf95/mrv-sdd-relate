// Impact: a target box with autocomplete, grouped lists, and a graph with the target in the centre.
// Clicking an item highlights the `via` chain that connects it to the target.
import { api } from "./api.js";
import { ZOOM, chainOf, cyStyle, declutter, elementsOf, smoothZoom } from "./cystyle.js";
import { h, labelColor } from "./dom.js";

const GROUPS = [
  ["specs", "Specs"],
  ["sections", "Sections"],
  ["milestones", "Milestones"],
  ["tables", "Tables and columns"],
  ["features", "Features"],
  ["files", "Files"],
  ["tasks_open", "Tasks (open)"],
  ["tasks_done", "Tasks (done)"],
  ["deviations", "Deviations"],
  ["tests", "Tests"],
  ["commits", "Commits"],
];
const SHOWN = 8; // items per group before "show all"

export function mount(el, arg) {
  let cy = null;
  let data = null;

  const input = h("input", {
    type: "search",
    list: "impact-targets",
    placeholder: "table, section, file or feature",
    "aria-label": "Impact target",
    value: arg || "",
  });
  const options = h("datalist", { id: "impact-targets" });
  const go = h("button", { type: "button" }, "Show impact");
  const err = h("div", { class: "err" });
  const choices = h("div", { class: "choices" });
  const lists = h("div", { class: "groups" });
  const chain = h("div", { class: "chain-note muted small" }, "Click an item to see how it connects to the target.");
  const canvas = h("div", { id: "cy" });
  el.append(
    h("div", { class: "bar" }, h("h2", {}, "Impact"), input, options, go),
    err,
    choices,
    h("div", { class: "split impact" }, h("div", {}, canvas, chain), lists),
  );

  api
    .targets()
    .then((t) => {
      options.replaceChildren(...t.map((n) => h("option", { value: n.id }, n.label)));
    })
    .catch(() => {});

  function item(group, it) {
    const row = h(
      "button",
      { type: "button", class: "item", "data-id": it.id },
      h("span", { class: "swatch", style: { background: labelColor(it.label) } }),
      h("span", { class: "id" }, it.id),
      it.title && it.title !== it.id ? h("span", { class: "muted small" }, it.title) : null,
      it.status ? h("span", { class: "tag" }, it.status) : null,
    );
    row.addEventListener("click", () => select(it));
    return row;
  }

  function renderLists() {
    lists.replaceChildren();
    for (const [key, title] of GROUPS) {
      const items = data.groups[key] || [];
      const head = h("h3", {}, title, h("span", { class: "pill" }, String(data.counts[key] ?? items.length)));
      const body = h("div", { class: "items" }, items.slice(0, SHOWN).map((it) => item(key, it)));
      const box = h("section", { class: "group", "data-group": key }, head, body);
      if (!items.length) box.append(h("div", { class: "muted small" }, "none"));
      if (items.length > SHOWN) {
        const more = h("button", { type: "button", class: "link" }, `Show all ${items.length}`);
        more.addEventListener("click", () => {
          body.replaceChildren(...items.map((it) => item(key, it)));
          more.remove();
        });
        box.append(more);
      }
      lists.append(box);
    }
  }

  function clearChain() {
    if (!cy) return;
    cy.elements().removeClass("dim chain");
    chain.textContent = "Click an item to see how it connects to the target.";
    for (const b of el.querySelectorAll(".item.on")) b.classList.remove("on");
  }

  function select(it) {
    clearChain();
    for (const b of el.querySelectorAll(`.item[data-id="${CSS.escape(it.id)}"]`)) b.classList.add("on");
    if (!cy) return;
    const { nodes, edges } = chainOf(it.via || [], it.id);
    cy.elements().addClass("dim");
    for (const id of nodes) cy.getElementById(id).removeClass("dim").addClass("chain");
    for (const id of edges) cy.getElementById(id).removeClass("dim").addClass("chain");
    const via = it.via || [];
    chain.replaceChildren(
      h("strong", {}, "Chain: "),
      via.length ? via.join(" ") : `${data.target.id} (direct)`,
    );
  }

  function draw(graph, targetId) {
    if (cy) cy.destroy();
    cy = cytoscape({ container: canvas, elements: elementsOf(graph), style: cyStyle(), ...ZOOM });
    smoothZoom(cy);
    cy.getElementById(targetId).addClass("target");
    // a wide impact (a hub table reaches 100+ nodes) gets small nodes and labels on hubs only; the
    // target always keeps its label
    if (declutter(cy, 60, 10)) cy.getElementById(targetId).removeClass("nolabel");
    cy.layout({
      name: "breadthfirst",
      roots: cy.getElementById(targetId),
      circle: true,
      directed: false,
      spacingFactor: 1.5,
      avoidOverlap: true,
      animate: false,
      fit: true,
      padding: 24,
    }).run();
    cy.on("tap", "node", (e) => {
      const id = e.target.id();
      const found = Object.values(data.groups).flat().find((x) => x.id === id);
      if (found) select(found);
      else clearChain();
    });
    cy.on("tap", (e) => {
      if (e.target === cy) clearChain();
    });
  }

  async function run(target) {
    err.textContent = "";
    choices.replaceChildren();
    if (!target) return;
    try {
      data = await api.impact(target);
      let graph;
      try {
        graph = await api.preset(`impact:${data.target.id}`);
      } catch {
        graph = { nodes: [], edges: [] };
      }
      if (!graph.nodes.some((n) => n.id === data.target.id)) {
        graph.nodes.push({ id: data.target.id, label: data.target.label, title: data.target.title, props: {} });
      }
      input.value = data.target.id;
      history.replaceState(null, "", `#impact/${encodeURIComponent(data.target.id)}`);
      renderLists();
      draw(graph, data.target.id);
      clearChain();
    } catch (e) {
      data = null;
      lists.replaceChildren();
      if (cy) cy.destroy();
      cy = null;
      if (e.code === "ambiguous_target") {
        choices.append(h("div", {}, `"${target}" matches more than one thing. Pick one:`));
        for (const c of e.details.candidates || []) {
          const b = h("button", { type: "button", class: "choice" }, c);
          b.addEventListener("click", () => run(c));
          choices.append(b);
        }
      } else err.textContent = e.message;
    }
  }

  go.addEventListener("click", () => run(input.value.trim()));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") run(input.value.trim());
  });

  const onTheme = () => {
    if (cy) cy.style(cyStyle());
  };
  window.addEventListener("themechange", onTheme);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", onTheme);
  if (arg) run(arg);
  else chain.textContent = "Type a table, section, file or feature name; the list suggests IDs.";

  return () => {
    window.removeEventListener("themechange", onTheme);
    matchMedia("(prefers-color-scheme: dark)").removeEventListener("change", onTheme);
    if (cy) cy.destroy();
  };
}
