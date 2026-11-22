// Shell: five tabs, hash routing (`#tab/<encoded id>`), theme toggle. Views live in their own
// modules and export `mount(el, arg) -> cleanup | undefined`.
import { api } from "./api.js";
import * as board from "./board.js";
import * as graph from "./graph.js";
import * as query from "./query.js";

const placeholder = (name, note) => ({
  mount(el) {
    const d = document.createElement("div");
    d.className = "placeholder";
    d.textContent = `${name}: ${note}`;
    el.append(d);
  },
});

const TABS = [
  ["board", "Board", board],
  ["graph", "Graph", graph],
  ["impact", "Impact", placeholder("Impact", "coming in the next milestone (M05b).")],
  ["explain", "Explain", placeholder("Explain", "coming in the next milestone (M05b).")],
  ["query", "Query", query],
];

const view = document.getElementById("view");
const nav = document.getElementById("tabs");
const select = document.getElementById("tabs-select");
let cleanup = null;

// "#impact/table%3Aattachments" -> ["impact", "table:attachments"]
export function parseHash(hash) {
  const raw = hash.replace(/^#/, "");
  const slash = raw.indexOf("/");
  const tab = slash < 0 ? raw : raw.slice(0, slash);
  let arg = slash < 0 ? "" : raw.slice(slash + 1);
  try {
    arg = decodeURIComponent(arg);
  } catch {
    /* keep the raw text */
  }
  return { tab: TABS.some((t) => t[0] === tab) ? tab : "board", arg };
}

export function go(tab, arg) {
  location.hash = arg ? `#${tab}/${encodeURIComponent(arg)}` : `#${tab}`;
}

for (const [key, label] of TABS) {
  const a = document.createElement("a");
  a.href = `#${key}`;
  a.dataset.tab = key;
  a.textContent = label;
  nav.append(a);
  select.append(new Option(label, key));
}
select.addEventListener("change", () => go(select.value));

function render() {
  const { tab, arg } = parseHash(location.hash);
  if (cleanup) cleanup();
  cleanup = null;
  view.replaceChildren();
  for (const a of nav.children) {
    if (a.dataset.tab === tab) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  select.value = tab;
  const mod = TABS.find((t) => t[0] === tab)[2];
  cleanup = mod.mount(view, arg) || null;
}
window.addEventListener("hashchange", render);

// Theme: follows the system until the toggle is used.
const root = document.documentElement;
try {
  const saved = localStorage.getItem("sdd-theme");
  if (saved) root.dataset.theme = saved;
} catch {
  /* storage blocked */
}
document.getElementById("theme").addEventListener("click", () => {
  const dark =
    root.dataset.theme === "dark" ||
    (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("sdd-theme", root.dataset.theme);
  } catch {
    /* storage blocked */
  }
  window.dispatchEvent(new Event("themechange"));
});

api
  .health()
  .then((h) => {
    document.getElementById("sync").textContent = h.project ? `${h.project} · ${h.mode}` : h.mode;
  })
  .catch(() => {});

render();
