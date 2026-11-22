// Static backend (SPEC-07 §1 rule 5, SPEC-11 §6): the dashboard on GitHub Pages, with no server.
// Answers are the JSON files `sdd site` wrote under data/ (the daemon's own answers, computed at
// build time). The Query tab runs in Relate's WASM build in a worker when it loads; otherwise it
// answers the example queries from data/ and refuses the rest. Replay animates the recorded events.
// All URLs are relative to this module, so the site works under any Pages sub-path.

const ROOT = new URL("./", import.meta.url);
const WASM_WAIT_MS = 15000;
const QUERY_MS = 5000;
const REPLAY_MS = 600;
const NO_TARGET = "The static demo has answers for the listed targets only. Pick one from the list.";

function fail(code, message, details = {}) {
  const e = new Error(message);
  e.code = code;
  e.details = details;
  return e;
}

const cache = new Map();
function load(path) {
  if (!cache.has(path)) {
    const p = fetch(new URL(path, ROOT)).then((r) => {
      if (!r.ok) throw fail("node_not_found", `${path}: HTTP ${r.status}`);
      return r.json();
    });
    p.catch(() => cache.delete(path));
    cache.set(path, p);
  }
  return cache.get(path);
}
const clone = (v) => JSON.parse(JSON.stringify(v));
const norm = (cypher) => cypher.split(/\s+/).filter(Boolean).join(" ");

async function answer(kind, key) {
  const index = await load("data/index.json");
  const file = index[kind] && index[kind][key];
  if (!file) return null;
  return load(`data/${kind}/${file}`);
}

// ---------------------------------------------------------------- the graph (graph.json)

// schema.LABELS minus DEFAULT_HIDDEN (service/api_views.py), in the order /api/graph walks them.
const DEFAULT_LABELS = [
  "Spec", "Section", "Milestone", "Task", "Deviation", "Commit", "File", "Folder", "Doc", "Feature",
  "Domain", "Table", "Column", "AcceptanceCheck",
];
const MAX_LIMIT = 2000;
const MAX_DEPTH = 3;
const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

let graphCache = null;
function graphData() {
  if (!graphCache) {
    graphCache = load("data/graph.json").then((g) => {
      const nodes = new Map(g.nodes.map((n) => [n.id, n]));
      const out = new Map();
      const inn = new Map();
      for (const e of g.edges) {
        if (!out.has(e.source)) out.set(e.source, []);
        out.get(e.source).push(e);
        if (!inn.has(e.target)) inn.set(e.target, []);
        inn.get(e.target).push(e);
      }
      return { nodes, edges: g.edges, out, in: inn, list: g.nodes };
    });
    graphCache.catch(() => (graphCache = null));
  }
  return graphCache;
}

// api_views.graph: nodes by label then id up to `limit`, or a breadth-first walk from `focus`.
async function graph({ labels = [], focus, depth = 1, limit = 300 } = {}) {
  const g = await graphData();
  const known = new Set(g.list.map((n) => n.label));
  const wanted = labels.length ? labels : DEFAULT_LABELS;
  const unknown = wanted.filter((l) => !known.has(l) && !DEFAULT_LABELS.includes(l));
  if (unknown.length) throw fail("invalid_input", `Unknown label(s): ${unknown.join(", ")}.`);
  if (!(limit >= 1 && limit <= MAX_LIMIT)) throw fail("invalid_input", `limit must be 1 to ${MAX_LIMIT}.`);
  if (!(depth >= 1 && depth <= MAX_DEPTH)) throw fail("invalid_input", `depth must be 1 to ${MAX_DEPTH}.`);
  const nodes = new Map();
  if (focus == null) {
    for (const label of wanted) {
      const room = limit - nodes.size;
      if (room <= 0) break;
      for (const n of g.list.filter((x) => x.label === label).sort(byId).slice(0, room)) nodes.set(n.id, n);
    }
  } else {
    const root = g.nodes.get(focus);
    if (!root) throw fail("node_not_found", `No node ${focus}.`, { id: focus });
    nodes.set(root.id, root);
    let frontier = [root.id];
    for (let hop = 0; hop < depth; hop++) {
      const found = [];
      for (const id of frontier) {
        for (const e of g.out.get(id) || []) found.push(g.nodes.get(e.target));
        for (const e of g.in.get(id) || []) found.push(g.nodes.get(e.source));
      }
      frontier = [];
      for (const n of found.filter(Boolean).sort(byId)) {
        if (nodes.has(n.id) || !wanted.includes(n.label)) continue;
        if (nodes.size >= limit) break;
        nodes.set(n.id, n);
        frontier.push(n.id);
      }
      if (!frontier.length || nodes.size >= limit) break;
    }
  }
  const edges = g.edges
    .filter((e) => nodes.has(e.source) && nodes.has(e.target))
    .sort((a, b) =>
      a.source !== b.source ? (a.source < b.source ? -1 : 1) : a.target !== b.target ? (a.target < b.target ? -1 : 1) : a.type < b.type ? -1 : a.type > b.type ? 1 : 0,
    );
  return { nodes: [...nodes.values()].sort(byId), edges };
}

// api_views.node: one node with its relationships grouped by type.
async function node(id) {
  const g = await graphData();
  const n = g.nodes.get(id);
  if (!n) throw fail("node_not_found", `No node ${id}.`, { id });
  const grouped = {};
  const add = (type, direction, other) => {
    (grouped[type] ||= []).push({ direction, id: other.id, label: other.label, title: other.title, props: other.props });
  };
  for (const e of g.out.get(id) || []) add(e.type, "out", g.nodes.get(e.target));
  for (const e of g.in.get(id) || []) add(e.type, "in", g.nodes.get(e.source));
  const relationships = {};
  for (const type of Object.keys(grouped).sort()) {
    relationships[type] = grouped[type].sort((a, b) =>
      a.direction !== b.direction ? (a.direction < b.direction ? -1 : 1) : a.id < b.id ? -1 : a.id > b.id ? 1 : 0,
    );
  }
  return { id: n.id, label: n.label, props: n.props, relationships };
}

async function targets() {
  const g = await graphData();
  return g.list
    .filter((n) => ["Table", "Feature", "File", "Section"].includes(n.label))
    .map((n) => ({ id: n.id, label: n.label, title: n.title }));
}

// ---------------------------------------------------------------- precomputed answers

// A typed target → one indexed ID: exact, then a unique case-insensitive match on the ID's tail or
// the node's title (the daemon's own forms of a bare name, SPEC-06 §2).
async function resolveTarget(raw) {
  const index = await load("data/index.json");
  const keys = Object.keys(index.impact);
  const text = String(raw || "").trim();
  if (!text) throw fail("invalid_input", "target must be a non-empty string.");
  if (index.impact[text]) return text;
  const g = await graphData();
  const t = text.toLowerCase();
  const found = keys.filter((k) => {
    const lower = k.toLowerCase();
    const title = String((g.nodes.get(k) || {}).title || "").toLowerCase();
    return lower === t || lower.endsWith(`:${t}`) || lower.endsWith(`#${t}`) || title === t;
  });
  if (found.length === 1) return found[0];
  if (found.length > 1) {
    const candidates = found.sort();
    throw fail(
      "ambiguous_target",
      `${JSON.stringify(text)} names ${candidates.length} nodes: repeat with one of ${candidates.join(", ")}.`,
      { target: text, candidates },
    );
  }
  throw fail("node_not_found", NO_TARGET, { target: text });
}

async function impact(target) {
  return clone(await answer("impact", await resolveTarget(target)));
}

async function explain(path) {
  const index = await load("data/index.json");
  const text = String(path || "").trim().replace(/^file:/, "").replace(/\\/g, "/").replace(/^\.\//, "");
  if (!text) throw fail("invalid_input", "path must be a non-empty string.");
  const paths = Object.keys(index.explain);
  let hits = paths.includes(text) ? [text] : paths.filter((p) => p.endsWith(`/${text}`) || p === text);
  if (hits.length === 0) {
    const lower = text.toLowerCase();
    hits = paths.filter((p) => p.toLowerCase() === lower);
  }
  if (hits.length === 1) return clone(await answer("explain", hits[0]));
  if (hits.length > 1) {
    const candidates = hits.sort().map((p) => `file:${p}`);
    throw fail("ambiguous_target", `${JSON.stringify(text)} names ${candidates.length} files: repeat with one of ${candidates.join(", ")}.`, {
      target: text,
      candidates,
    });
  }
  throw fail("node_not_found", NO_TARGET, { target: text });
}

async function preset(name) {
  const hit = await answer("preset", String(name || "").trim());
  if (!hit) throw fail("node_not_found", `The static demo has no preset ${JSON.stringify(name)}. Pick one from the list.`, { preset: name });
  return clone(hit);
}

// ---------------------------------------------------------------- Replay (M08.5)

let replayState = null; // {boards, milestones, timer, ticks, index, done}
const listeners = new Set();
const endListeners = new Set();

const boardOrder = (board) => new Map(Object.values(board.columns).flat().map((t, i) => [t.id, i]));

function applyTask(state, d) {
  const board = state.boards[d.milestone_id];
  if (!board) return;
  let task = null;
  for (const col of Object.values(board.columns)) {
    const at = col.findIndex((t) => t.id === d.id);
    if (at >= 0) task = col.splice(at, 1)[0];
  }
  if (!task) return;
  task.claimed_by = d.claimed_by ?? task.claimed_by;
  if (d.status === "done") task.completed_by = d.completed_by ?? task.claimed_by;
  const col = board.columns[d.status] || (board.columns[d.status] = []);
  col.push(task);
  const order = state.order[d.milestone_id];
  col.sort((a, b) => order.get(a.id) - order.get(b.id));
}

function applyEvent(state, ev) {
  if (ev.type === "task") applyTask(state, ev.data);
  if (ev.type === "milestone" && state.boards[ev.data.id]) state.boards[ev.data.id].milestone.status = ev.data.status;
}

function replayMilestones(base) {
  if (!replayState) return base;
  return base.map((m) => {
    const board = replayState.boards[m.id];
    if (!board) return m;
    const c = board.columns;
    return { ...m, status: board.milestone.status, done: c.done.length, claimed: c.claimed.length };
  });
}

async function startReplay(milestone) {
  stopReplay();
  const data = await load("data/replay.json");
  const ids = Object.keys(data.start);
  const state = {
    boards: clone(data.start),
    order: Object.fromEntries(ids.map((m) => [m, boardOrder(data.start[m])])),
    ticks: [],
    index: 0,
    timer: null,
  };
  for (const ev of data.events) {
    const last = state.ticks[state.ticks.length - 1];
    if (last && last.tick === ev.tick) last.events.push(ev);
    else state.ticks.push({ tick: ev.tick, events: [ev] });
  }
  replayState = state;
  const first = ids.includes(milestone) ? milestone : ids[0];
  state.timer = setInterval(() => {
    if (replayState !== state) return clearInterval(state.timer);
    const next = state.ticks[state.index++];
    if (!next) {
      clearInterval(state.timer);
      state.timer = null;
      for (const fn of endListeners) fn();
      return;
    }
    for (const ev of next.events) {
      applyEvent(state, ev);
      for (const fn of [...listeners]) fn(ev.type, ev.data);
    }
  }, REPLAY_MS);
  return { milestone: first };
}

function stopReplay() {
  if (replayState && replayState.timer) clearInterval(replayState.timer);
  replayState = null;
}

// ---------------------------------------------------------------- Relate WASM (the Query tab)

const wasm = { worker: null, ready: null, info: null, reason: "", pending: new Map(), seq: 0 };

function supportsWasm() {
  try {
    return typeof WebAssembly === "object" && typeof Worker === "function";
  } catch {
    return false;
  }
}

// Start a fresh worker; `wasm.ready` resolves to its info or null (the reason is in wasm.reason).
function spawn() {
  wasm.info = null;
  wasm.pending = new Map();
  const worker = new Worker(new URL("relate-worker.js", ROOT), { type: "module" });
  wasm.worker = worker;
  wasm.ready = new Promise((resolve) => {
    const giveUp = setTimeout(() => {
      wasm.reason = `Relate WASM was not ready within ${WASM_WAIT_MS / 1000} s`;
      worker.terminate();
      if (wasm.worker === worker) wasm.worker = null;
      resolve(null);
    }, WASM_WAIT_MS);
    const done = (info, reason) => {
      clearTimeout(giveUp);
      if (reason) {
        wasm.reason = reason;
        worker.terminate();
        if (wasm.worker === worker) wasm.worker = null;
      }
      wasm.info = info;
      resolve(info);
    };
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === "ready") return done(m);
      if (m.type === "failed") return done(null, m.reason);
      const p = wasm.pending.get(m.id);
      if (!p) return;
      wasm.pending.delete(m.id);
      clearTimeout(p.timer);
      if (m.dead) respawn();
      if (m.ok) p.resolve(m.result);
      else p.reject(fail(m.error.code, m.error.message));
    };
    worker.onerror = (e) => done(null, e.message || "the Relate WASM worker failed to start");
  });
}

function respawn() {
  const old = wasm.worker;
  if (old) old.terminate();
  for (const p of wasm.pending.values()) {
    clearTimeout(p.timer);
    p.reject(fail("query_timeout", "The query was stopped. Add a LIMIT or narrow the pattern.", {}));
  }
  spawn();
}

async function wasmQuery(cypher, params) {
  const info = await wasm.ready;
  if (!info || !wasm.worker) throw fail("query_timeout", "Relate WASM is restarting; try again in a few seconds.");
  const id = ++wasm.seq;
  const worker = wasm.worker;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      wasm.pending.delete(id);
      reject(fail("query_timeout", `The query ran longer than ${QUERY_MS / 1000} s. Add a LIMIT or narrow the pattern.`));
      if (wasm.worker === worker) respawn();
    }, QUERY_MS);
    wasm.pending.set(id, { resolve, reject, timer });
    worker.postMessage({ id, cypher, params });
  });
}

// The two follow-up queries behind "Show as graph" (query.js), answered from graph.json when
// there is no WASM.
const SHOW_NODES = "MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, labels(n)[0] AS label";
const SHOW_EDGES = "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS s, type(r) AS t, b.id AS d";

async function precomputedQuery(cypher, params) {
  const key = norm(cypher);
  const hit = await answer("query", key);
  if (hit) return clone(hit);
  const ids = params && Array.isArray(params.ids) ? new Set(params.ids) : null;
  if (ids && (key === SHOW_NODES || key === SHOW_EDGES)) {
    const g = await graphData();
    if (key === SHOW_NODES) {
      const rows = g.list.filter((n) => ids.has(n.id)).sort(byId).map((n) => [n.id, n.label]);
      return { columns: ["id", "label"], rows, truncated: false };
    }
    const rows = g.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => [e.source, e.type, e.target]);
    return { columns: ["s", "t", "d"], rows, truncated: false };
  }
  throw fail("query_rejected", "Only the presets run in the static demo.");
}

// ---------------------------------------------------------------- the backend

export async function create() {
  const manifest = await load("data/manifest.json");
  if (manifest.wasm && supportsWasm()) {
    try {
      spawn();
    } catch (e) {
      wasm.ready = Promise.resolve(null);
      wasm.reason = String((e && e.message) || e);
    }
  } else {
    wasm.ready = Promise.resolve(null);
    wasm.reason = manifest.wasm ? "this browser has no WebAssembly or module workers" : "this build has no Relate WASM files";
  }
  const settled = wasm.ready.then(() => wasm.info);

  return {
    name: () => (wasm.info ? "wasm" : "precomputed"),
    // {backend, nodes, ms, version, reason}: resolves once the WASM attempt has ended either way
    engine: async () => {
      const info = await settled;
      return info
        ? { backend: "wasm", nodes: info.nodes, ms: info.ms, version: info.version, reason: "" }
        : { backend: "precomputed", nodes: manifest.counts.nodes, ms: 0, version: "", reason: wasm.reason };
    },
    wantsWasm: manifest.wasm && supportsWasm(),
    async health(opts = {}) {
      const h = clone(await load("data/health.json"));
      if (opts.settled) await settled;
      if (wasm.info) h.public_query = "guarded";
      return h;
    },
    milestones: async () => replayMilestones(clone(await load("data/milestones.json"))),
    examples: async () => clone(await load("examples.json")),
    presets: async () => clone(await load("data/presets.json")),
    preset,
    async board(milestone) {
      if (replayState && milestone && replayState.boards[milestone]) return clone(replayState.boards[milestone]);
      const index = await load("data/index.json");
      let key = milestone || "default";
      if (!index.board[key]) key = Object.keys(index.board).find((k) => k.toLowerCase() === key.toLowerCase()) || key;
      const hit = await answer("board", key);
      if (!hit) throw fail("milestone_not_found", `No milestone ${milestone}.`, { id: milestone });
      return clone(hit);
    },
    graph,
    node,
    targets,
    impact,
    explain,
    async query(cypher, params = {}) {
      await settled;
      if (wasm.info) return wasmQuery(cypher, params);
      return precomputedQuery(cypher, params);
    },
    // No stream: the listeners only hear the replay.
    events(onEvent, onState) {
      listeners.add(onEvent);
      onState(false);
      return () => listeners.delete(onEvent);
    },
    replay: {
      start: startReplay,
      stop: stopReplay,
      running: () => replayState !== null,
      onEnd(fn) {
        endListeners.add(fn);
        return () => endListeners.delete(fn);
      },
    },
  };
}
