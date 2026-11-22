// Named presets (SPEC-06 §5, endpoint 13): a picker with a value box for the preset's placeholder.
import { api } from "./api.js";
import { h } from "./dom.js";

// "lineage:<section>" + "SPEC-02#2" -> "lineage:SPEC-02#2"; a preset without params is its name.
export function presetName(preset, value) {
  return preset.params.length ? preset.name.replace(/<[^>]+>/, value.trim()) : preset.name;
}

// Returns {el, list()}; `onRun(name)` gets the full preset name. The Graph tab deep-links to a
// preset with `#graph/preset:<name>`.
export function picker(onRun) {
  let list = [];
  const select = h("select", { "aria-label": "Preset" }, new Option("Presets", ""));
  const value = h("input", { type: "text", hidden: true, "aria-label": "Preset value" });
  const go = h("button", { type: "button", hidden: true }, "Show");
  const el = h("span", { class: "presetbar" }, select, value, go);

  const current = () => list.find((p) => p.name === select.value);
  select.addEventListener("change", () => {
    const p = current();
    value.hidden = go.hidden = !p;
    if (!p) return;
    value.placeholder = p.params.join(", ") || "";
    value.hidden = p.params.length === 0;
    value.title = p.description;
    if (!p.params.length) onRun(p.name);
    else value.focus();
  });
  const run = () => {
    const p = current();
    if (p && (value.value.trim() || !p.params.length)) onRun(presetName(p, value.value));
  };
  go.addEventListener("click", run);
  value.addEventListener("keydown", (e) => {
    if (e.key === "Enter") run();
  });

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
