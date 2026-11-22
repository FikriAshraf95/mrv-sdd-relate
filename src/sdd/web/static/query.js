// Query: a read-only Cypher box, example queries, a results table and "Show as graph".
import { api } from "./api.js";
import { cyStyle, elementsOf } from "./cystyle.js";
import { h } from "./dom.js";
import { picker } from "./presets.js";

const EXAMPLES = [
  ["Open tasks", "MATCH (t:Task) WHERE t.status <> 'done' RETURN t.id AS id, t.title AS title, t.status AS status ORDER BY id LIMIT 50"],
  ["Milestones", "MATCH (m:Milestone) RETURN m.id AS id, m.title AS title, m.status AS status ORDER BY m.order"],
  ["Deviations", "MATCH (d:Deviation) RETURN d.id AS id, d.title AS title, d.status AS status ORDER BY id"],
  ["Tasks with their milestone", "MATCH (m:Milestone)-[r:INCLUDES]->(t:Task) RETURN m, r, t LIMIT 40"],
  ["Spec sections", "MATCH (s:Spec)-[r]->(c:Section) RETURN s, r, c LIMIT 60"],
  ["Label counts", "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC"],
];

const isNode = (v) => v && typeof v === "object" && !Array.isArray(v) && typeof v.id === "string";

export function mount(el) {
  let cy = null;
  const box = h("textarea", { class: "cypher", "aria-label": "Cypher", spellcheck: "false" });
  box.value = EXAMPLES[0][1];
  const pick = h("select", { "aria-label": "Example queries" }, new Option("Examples", ""), ...EXAMPLES.map(([t], i) => new Option(t, String(i))));
  const run = h("button", { type: "button", class: "primary" }, "Run");
  const graphBtn = h("button", { type: "button", hidden: true }, "Show as graph");
  const status = h("span", { class: "muted small" });
  const err = h("div", { class: "err" });
  const out = h("div");
  const canvas = h("div", { id: "cy", hidden: true });
  const bar = h("div", { class: "bar mt" }, run, graphBtn, status);
  el.append(
    h("div", { class: "bar" }, h("h2", {}, "Query"), pick, h("span", { class: "grow" })),
    box,
    bar,
    err,
    out,
    canvas,
  );

  pick.addEventListener("change", () => {
    if (pick.value !== "") box.value = EXAMPLES[Number(pick.value)][1];
    pick.value = "";
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run.click();
  });

  let result = null;

  function draw(data) {
    canvas.hidden = false;
    if (cy) cy.destroy();
    cy = cytoscape({
      container: canvas,
      elements: elementsOf(data),
      layout: { name: "cose", animate: false, padding: 24 },
      style: cyStyle(),
    });
  }

  // Presets-only mode (public process with SDD_PUBLIC_QUERY=presets, SPEC-09 §2 rule 5): the box is
  // display-only and only named presets run.
  async function runPreset(name) {
    err.textContent = "";
    out.replaceChildren();
    graphBtn.hidden = true;
    status.textContent = "Running…";
    try {
      const data = await api.preset(name);
      status.textContent = `${name}: ${data.nodes.length} nodes, ${data.edges.length} edges`;
      draw(data);
    } catch (e) {
      status.textContent = "";
      err.textContent = e.message;
    }
  }

  bar.append(picker(runPreset).el); // the presets also work as examples when Cypher is allowed
  api
    .health()
    .then((hl) => {
      if (hl.mode !== "public" || hl.public_query !== "presets") return;
      box.readOnly = true;
      box.value = "Only the named presets run on this server. Pick one below.";
      pick.hidden = run.hidden = true;
    })
    .catch(() => {});

  function table(res) {
    const cell = (v) => (v === null || v === undefined ? "" : typeof v === "object" ? (isNode(v) ? v.id : JSON.stringify(v)) : String(v));
    return h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, res.columns.map((c) => h("th", {}, c)))),
        h("tbody", {}, res.rows.map((r) => h("tr", {}, r.map((v) => h("td", {}, cell(v)))))),
      ),
    );
  }

  run.addEventListener("click", async () => {
    err.textContent = "";
    out.replaceChildren();
    canvas.hidden = true;
    graphBtn.hidden = true;
    status.textContent = "Running…";
    try {
      result = await api.query(box.value);
      status.textContent = `${result.rows.length} row${result.rows.length === 1 ? "" : "s"}${result.truncated ? " (truncated)" : ""}`;
      out.replaceChildren(table(result));
      graphBtn.hidden = !result.rows.some((r) => r.some(isNode));
    } catch (e) {
      status.textContent = "";
      err.textContent = e.message;
    }
  });

  graphBtn.addEventListener("click", async () => {
    err.textContent = "";
    const ids = [...new Set(result.rows.flatMap((r) => r.filter(isNode).map((n) => n.id)))].slice(0, 100);
    try {
      const nodes = await api.query("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, labels(n)[0] AS label", { ids });
      const edges = await api.query(
        "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS s, type(r) AS t, b.id AS d",
        { ids },
      );
      draw({
        nodes: nodes.rows.map(([id, label]) => ({ id, label, title: id })),
        edges: edges.rows.map(([source, type, target]) => ({ source, type, target })),
      });
    } catch (e) {
      err.textContent = e.message;
    }
  });

  const onTheme = () => cy && cy.style(cyStyle());
  window.addEventListener("themechange", onTheme);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", onTheme);
  return () => {
    window.removeEventListener("themechange", onTheme);
    matchMedia("(prefers-color-scheme: dark)").removeEventListener("change", onTheme);
    if (cy) cy.destroy();
  };
}
