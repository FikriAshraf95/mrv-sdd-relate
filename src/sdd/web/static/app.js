// Shell: five tabs, hash routing (`#tab/<encoded id>`), theme toggle. Views live in their own
// modules and export `mount(el, arg) -> cleanup | undefined`.
import { toggleTheme } from "./theme.js"; // its import applies data-theme before the views paint
import { api, getToken, onUnauthorized, setToken } from "./api.js";
import * as board from "./board.js";
import { h } from "./dom.js";
import * as explain from "./explain.js";
import * as graph from "./graph.js";
import * as impact from "./impact.js";
import * as query from "./query.js";

const TABS = [
  ["board", "Board", board],
  ["graph", "Graph", graph],
  ["impact", "Impact", impact],
  ["explain", "Explain", explain],
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

// SDD_TOKEN: on a 401 the shell asks for the token once and re-renders; "Forget token" clears it.
const forget = document.getElementById("forget");
const syncForget = () => {
  forget.hidden = !getToken();
};
let asking = false;
onUnauthorized(() => {
  if (asking) return;
  asking = true;
  const field = h("input", { type: "password", autocomplete: "off", "aria-label": "Token", placeholder: "SDD_TOKEN" });
  const form = h(
    "form",
    { class: "login" },
    h("p", {}, "This server needs a token. It stays in this tab only and is sent as a header."),
    field,
    h("button", { type: "submit", class: "primary" }, "Unlock"),
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    setToken(field.value.trim());
    asking = false;
    syncForget();
    render();
  });
  view.replaceChildren(form);
  field.focus();
});
forget.addEventListener("click", (e) => {
  e.preventDefault();
  setToken("");
  syncForget();
  render();
});
syncForget();

// Theme: dark unless chosen otherwise (theme.js).
document.getElementById("theme").addEventListener("click", toggleTheme);

api
  .health()
  .then((h) => {
    document.getElementById("sync").textContent = h.project ? `${h.project} · ${h.mode}` : h.mode;
    if (h.base_url) {
      const foot = document.getElementById("foot");
      foot.textContent = h.base_url; // text, never markup
      foot.hidden = false;
    }
  })
  .catch(() => {});

// Static demo: say which engine answers (SPEC-11 §6), in the footer. Text only, never markup.
if (api.isStatic) {
  const foot = document.getElementById("foot");
  foot.textContent = "Static demo · loading Relate WASM…";
  foot.hidden = false;
  api
    .engine()
    .then((e) => {
      if (e.backend === "wasm") {
        foot.textContent = `Static demo · Relate WASM ${e.version} · ${e.nodes} nodes loaded in ${e.ms} ms`;
        foot.removeAttribute("title");
      } else {
        foot.textContent = "Static demo · precomputed answers";
        if (e.reason) foot.title = e.reason;
      }
    })
    .catch(() => {
      foot.textContent = "Static demo · precomputed answers";
    });
}

render();
