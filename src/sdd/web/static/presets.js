// Named presets (SPEC-06 §5, endpoint 13): a picker with a value box for the preset's placeholder.
import { api } from "./api.js";
import { h } from "./dom.js";

// "lineage:<section>" + "SPEC-02#2" -> "lineage:SPEC-02#2"; a preset without params is its name.
export function presetName(preset, value) {
  return preset.params.length ? preset.name.replace(/<[^>]+>/, value.trim()) : preset.name;
}

// What the value box offers for each placeholder: a loader returning [{value, text}].
const SOURCES = {
  id: async () => (await api.milestones()).map((m) => ({ value: m.id, text: m.title })),
  target: async () => (await api.targets()).map((n) => ({ value: n.id, text: `${n.label} ${n.title && n.title !== n.id ? n.title : ""}`.trim() })),
  path: async () =>
    (await api.targets()).filter((n) => n.label === "File").map((n) => ({ value: n.id.replace(/^file:/, ""), text: "File" })),
  section: async () => (await api.targets()).filter((n) => n.label === "Section").map((n) => ({ value: n.id, text: n.title || "" })),
  slug: async () =>
    (await api.targets()).filter((n) => n.label === "Feature").map((n) => ({ value: n.id.replace(/^feature:/, ""), text: n.title || "Feature" })),
};

const SHOWN = 80; // entries drawn at once; typing narrows the rest

// A searchable dropdown in the dashboard's own style (the native datalist popup cannot be styled):
// a text box and a listbox under it. Arrow keys move, Enter picks, Escape closes; typing filters on
// the value and the description. Returns {el, input, setItems(items), close()}; `onPick(value)` runs
// when an entry is chosen.
function combobox({ label, onPick, onEnter }) {
  let items = [];
  let shown = [];
  let active = -1;
  const id = `combo-${++combos}`;
  const input = h("input", {
    type: "text",
    autocomplete: "off",
    role: "combobox",
    "aria-label": label,
    "aria-autocomplete": "list",
    "aria-expanded": "false",
    "aria-controls": id,
  });
  const box = h("ul", { class: "listbox", id, role: "listbox", hidden: true });
  const el = h("span", { class: "combo" }, input, box);

  const open = () => {
    if (!items.length) return;
    box.hidden = false;
    input.setAttribute("aria-expanded", "true");
    render();
  };
  const close = () => {
    box.hidden = true;
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  };
  const mark = () => {
    [...box.children].forEach((li, i) => li.classList.toggle("on", i === active));
    const li = box.children[active];
    if (li) {
      input.setAttribute("aria-activedescendant", li.id);
      li.scrollIntoView({ block: "nearest" });
    }
  };
  function render() {
    const q = input.value.trim().toLowerCase();
    const hits = q ? items.filter((i) => `${i.value} ${i.text}`.toLowerCase().includes(q)) : items;
    shown = hits.slice(0, SHOWN);
    active = shown.length && q ? 0 : -1; // typing highlights the best match; just opening does not
    const rows = shown.map((i, n) =>
      h("li", { class: "opt", role: "option", id: `${id}-${n}`, "data-value": i.value }, h("span", { class: "v" }, i.value), i.text ? h("span", { class: "t" }, i.text) : null),
    );
    if (hits.length > shown.length) rows.push(h("li", { class: "more", "aria-hidden": "true" }, `${hits.length - shown.length} more, keep typing`));
    if (!hits.length) rows.push(h("li", { class: "more", "aria-hidden": "true" }, "No match"));
    box.replaceChildren(...rows);
    mark();
  }

  input.addEventListener("focus", open);
  input.addEventListener("click", open);
  input.addEventListener("input", () => {
    open();
    render();
  });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (box.hidden) return open();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % Math.max(1, shown.length);
      mark();
    } else if (e.key === "Enter") {
      if (!box.hidden && active >= 0 && shown[active]) {
        e.preventDefault();
        onPick(shown[active].value);
        close();
      } else onEnter();
    } else if (e.key === "Escape") close();
  });
  // mousedown, not click: the input would lose focus (and close the list) before a click lands
  box.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const li = e.target.closest(".opt");
    if (!li) return;
    onPick(li.dataset.value);
    close();
  });

  return {
    el,
    input,
    close,
    setItems(next) {
      items = next;
      if (document.activeElement === input) open();
    },
  };
}
let combos = 0;

// Returns {el, list()}; `onRun(name)` gets the full preset name. The Graph tab deep-links to a
// preset with `#graph/preset:<name>`.
export function picker(onRun) {
  let list = [];
  const select = h("select", { "aria-label": "Preset" }, new Option("Presets", ""));
  const go = h("button", { type: "button", hidden: true }, "Show");
  const value = combobox({
    label: "Preset value",
    onPick: (v) => {
      value.input.value = v;
      run();
    },
    onEnter: () => run(),
  });
  value.el.hidden = true;
  const el = h("span", { class: "presetbar" }, select, value.el, go);

  const current = () => list.find((p) => p.name === select.value);
  select.addEventListener("change", async () => {
    const p = current();
    value.el.hidden = go.hidden = !p;
    value.setItems([]);
    value.input.value = "";
    value.close();
    if (!p) return;
    value.input.placeholder = p.params.length ? `search ${p.params[0]}…` : "";
    value.el.hidden = p.params.length === 0;
    value.input.title = p.description;
    if (!p.params.length) return onRun(p.name);
    value.input.focus();
    try {
      const load = SOURCES[p.params[0]];
      const items = load ? await load() : [];
      if (current() === p) value.setItems(items); // the preset may have changed while the list loaded
    } catch {
      /* no list: the box still takes a typed value */
    }
  });
  function run() {
    const p = current();
    if (p && (value.input.value.trim() || !p.params.length)) onRun(presetName(p, value.input.value));
  }
  go.addEventListener("click", run);

  api
    .presets()
    .then((p) => {
      list = p;
      select.append(...p.map((x) => new Option(x.name, x.name)));
    })
    .catch(() => {});
  return { el, list: () => list };
}

export const PRESET_PREFIX = "preset:";
