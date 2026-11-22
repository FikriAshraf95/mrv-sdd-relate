// Data adapter (SPEC-07 §1 rule 5). Views call only this module. This is the HTTP backend; the
// static and WASM backends (M08) implement the same functions.

const enc = encodeURIComponent;

async function request(path, options) {
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

export const api = {
  health: () => request("/api/health"),
  milestones: () => request("/api/milestones"),
  board: (milestone) => request(`/api/board${qs({ milestone })}`),
  graph: ({ labels = [], focus, depth = 1, limit = 300 } = {}) =>
    request(`/api/graph${qs({ labels: labels.join(","), focus, depth, limit })}`),
  node: (id) => request(`/api/nodes/${enc(id)}`),
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
    if (typeof EventSource === "undefined") {
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

export const hashId = enc;
