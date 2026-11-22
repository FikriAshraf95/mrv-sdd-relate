// Small DOM helpers. Data is only ever set as text, never as markup.

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") el.className = v;
    else if (k === "style") Object.assign(el.style, v); // CSSOM, not an attribute (CSP)
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  return el;
}

// Text with `code` spans, as task titles are written in Markdown.
export function inline(text) {
  return String(text ?? "")
    .split(/(`[^`]+`)/)
    .filter(Boolean)
    .map((p) => (p.startsWith("`") && p.endsWith("`") ? h("code", {}, p.slice(1, -1)) : p));
}

export function agentColor(name) {
  let n = 0;
  for (const c of String(name)) n = (n * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${n} 52% 42%)`;
}

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#94a3b8";
}

// Every label of SPEC-02 §1 the graph view shows (Event and Meta never appear). Agent is off until
// asked for, as in /api/graph.
const KNOWN = [
  "Spec", "Section", "AcceptanceCheck", "Milestone", "Task", "Deviation", "Doc", "Folder",
  "File", "Commit", "Table", "Column", "Feature", "Domain", "Agent",
];
export const LABELS = KNOWN;
export const DEFAULT_LABELS = KNOWN.filter((l) => l !== "Agent");
export const labelColor = (label) => css(`--l-${KNOWN.includes(label) ? label : "other"}`);
