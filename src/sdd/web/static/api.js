// Data adapter (SPEC-07 §1 rule 5). Views call only this module. `api` is a facade over one
// backend, chosen once by <meta name="sdd-backend">: absent is the HTTP backend below (the daemon
// and `sdd public`); "static" is static.js (GitHub Pages: precomputed answers, plus Relate WASM
// for the Query tab when the browser can run it).

const enc = encodeURIComponent;
let targetsCache = null;

// SDD_TOKEN (SPEC-09 §2 rule 2): kept in sessionStorage only (this tab, gone when it closes), sent
// as a header, never in a URL or cookie. Storage can be blocked, so every access is guarded.
const TOKEN_KEY = "sdd-token";
export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}
export function setToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the token lasts until the next 401 */
  }
}
const unauthorizedHandlers = [];
export const onUnauthorized = (fn) => unauthorizedHandlers.push(fn);

async function request(path, options = {}) {
  const token = getToken();
  if (token) options = { ...options, headers: { ...options.headers, Authorization: `Bearer ${token}` } };
  const res = await fetch(path, options);
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  if (!res.ok) {
    const e = (body && body.error) || {};
    const err = new Error(e.message || `HTTP ${res.status}`);
    err.code = e.code || `http_${res.status}`;
    err.details = e.details || {};
    if (res.status === 401) for (const fn of unauthorizedHandlers) fn();
    throw err;
  }
  return body;
}

function qs(params) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${enc(v)}`)
    .join("&");
  return q ? `?${q}` : "";
}

const http = {
  health: () => request("/api/health"),
  milestones: () => request("/api/milestones"),
  board: (milestone) => request(`/api/board${qs({ milestone })}`),
  graph: ({ labels = [], focus, depth = 1, limit = 300 } = {}) =>
    request(`/api/graph${qs({ labels: labels.join(","), focus, depth, limit })}`),
  node: (id) => request(`/api/nodes/${enc(id)}`),
  impact: (target, depth = 3) => request(`/api/impact${qs({ target, depth })}`),
  explain: (path) => request(`/api/explain${qs({ path })}`),
  // IDs for the autocomplete and the file tree: one call per kind of target, cached.
  async targets() {
    if (!targetsCache) {
      targetsCache = request(
        `/api/graph${qs({ labels: "Table,Feature,File,Section", limit: 2000 })}`,
      ).then((g) => g.nodes.map((n) => ({ id: n.id, label: n.label, title: n.title })));
      targetsCache.catch(() => (targetsCache = null));
    }
    return targetsCache;
  },
  examples: () => request("examples.json"),
  presets: () => request("/api/presets"),
  preset: (name) => request(`/api/presets/${enc(name)}`),
  query: (cypher, params = {}) =>
    request("/api/query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ cypher, params }),
    }),

  // Live events: returns a close function. `onState(true|false)` reports whether the stream is up.
  events(onEvent, onState) {
    // EventSource cannot send headers: with a token the Board uses its polling fallback.
    if (typeof EventSource === "undefined" || getToken()) {
      onState(false);
      return () => {};
    }
    const es = new EventSource("/api/events");
    es.onopen = () => onState(true);
    es.onerror = () => onState(false);
    for (const type of ["task", "deviation", "graph_changed", "milestone"]) {
      es.addEventListener(type, (e) => {
        try {
          onEvent(type, JSON.parse(e.data));
        } catch {
          /* ignore a malformed event */
        }
      });
    }
    return () => es.close();
  },
};

const meta = document.querySelector('meta[name="sdd-backend"]');
const isStatic = Boolean(meta && meta.content === "static");
let chosen = null;
let current = null;
const backend = () =>
  (chosen ||= isStatic
    ? import("./static.js").then((m) => m.create()).then((b) => (current = b))
    : Promise.resolve((current = http)));
const via =
  (name) =>
  (...args) =>
    backend().then((b) => b[name](...args));

export const api = {
  health: via("health"),
  milestones: via("milestones"),
  board: via("board"),
  graph: via("graph"),
  node: via("node"),
  impact: via("impact"),
  explain: via("explain"),
  targets: via("targets"),
  examples: via("examples"),
  presets: via("presets"),
  preset: via("preset"),
  query: via("query"),
  events(onEvent, onState) {
    let close = null;
    let dead = false;
    backend().then((b) => {
      if (!dead) close = b.events(onEvent, onState);
    });
    return () => {
      dead = true;
      if (close) close();
    };
  },
  // "http" | "precomputed" | "wasm"; "precomputed" until the WASM worker is up
  backend: () => (isStatic ? (current ? current.name() : "precomputed") : "http"),
  isStatic,
  // static only: {backend, nodes, ms, version, reason}, resolved when the WASM attempt has ended
  engine: () => (isStatic ? backend().then((b) => b.engine()) : Promise.resolve(null)),
  // static only: Board Replay; null on the daemon and the public server
  replay: isStatic
    ? {
        start: (m) => backend().then((b) => b.replay.start(m)),
        stop: () => backend().then((b) => b.replay.stop()),
        running: () => Boolean(current && current.replay.running()),
        onEnd: (fn) => {
          let off = () => {};
          backend().then((b) => (off = b.replay.onEnd(fn)));
          return () => off();
        },
      }
    : null,
};

export const hashId = enc;
