// Relate WASM worker (SPEC-11 §6, M08.4): loads the sample's exported graph into an in-memory
// Relate database and answers guarded Cypher for the Query tab. A dedicated module worker, so a
// slow query never freezes the page (the page terminates it at the time limit).
//
// Messages in:  {id, cypher, params}
// Messages out: {type: "ready", nodes, relationships, ms, version}   once loaded and verified
//               {type: "failed", reason}                              could not load: the page falls back
//               {id, ok: true, result: {columns, rows, truncated}}
//               {id, ok: false, error: {code, message}, dead?: true}  dead: a wasm trap, the page respawns

const VERSION = "1.2.0"; // @relate/relate-wasm, pinned in .github/workflows/pages.yml
const MAX_ROWS = 100;
const MAX_HOPS = 4;
const MAX_CHARS = 20000;

// ---------------------------------------------------------------- the guard
// A port of the token rules of service/query_guard.py (SPEC-09 §3 step 1 and the hop bound):
// FORBIDDEN, TOKEN, tokenize(), check(), _check_hops() and _check_bound(), with the same error
// codes and messages. Steps 2 and 3 (rollback, snapshot) do not apply: the database is a private
// in-memory copy in the visitor's tab, and a write that slipped past would only change that copy.

const FORBIDDEN = new Set([
  "CREATE", "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "DROP", "LOAD", "FOREACH", "CALL", "USE",
]);

const TOKEN = new RegExp(
  [
    String.raw`(?<ws>\s+)`,
    String.raw`(?<line>//[^\n]*)`,
    String.raw`(?<block>/\*[\s\S]*?(?:\*/|$))`,
    String.raw`(?<str>'(?:[^'\\]|\\[\s\S])*(?:'|$)|"(?:[^"\\]|\\[\s\S])*(?:"|$))`,
    String.raw`(?<name>\`(?:[^\`]|\`\`)*(?:\`|$))`,
    String.raw`(?<word>[A-Za-z_][A-Za-z0-9_]*)`,
    String.raw`(?<num>\d+)`,
    String.raw`(?<op>\.\.|[\s\S])`,
  ].join("|"),
  "y",
);

class Rejected extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}
const reject = (message) => new Rejected("query_rejected", message);

function tokenize(cypher) {
  const out = [];
  TOKEN.lastIndex = 0;
  while (TOKEN.lastIndex < cypher.length) {
    const m = TOKEN.exec(cypher);
    if (!m) break;
    const kind = Object.keys(m.groups).find((k) => m.groups[k] !== undefined) || "op";
    if (kind === "ws" || kind === "line" || kind === "block") continue;
    out.push({ kind, text: m[0] });
  }
  return out;
}

function checkBound(tokens, star) {
  const rest = tokens.slice(star + 1, star + 4).map((t) => t.text);
  let low = null;
  if (rest.length && /^\d+$/.test(rest[0])) low = rest.shift();
  let high;
  if (!rest.length || rest[0] !== "..") {
    if (low === null) throw reject(`A variable-length pattern needs an upper bound: use *..${MAX_HOPS} at most.`);
    high = low; // *3 means exactly 3
  } else {
    high = rest.length > 1 && /^\d+$/.test(rest[1]) ? rest[1] : null;
    if (high === null) throw reject(`A variable-length pattern needs an upper bound: use *..${MAX_HOPS} at most.`);
  }
  if (Number(high) > MAX_HOPS) throw reject(`Variable-length patterns go at most ${MAX_HOPS} hops (*..${MAX_HOPS}).`);
}

function checkHops(tokens) {
  let depth = 0; // nesting of '[' inside the current relationship pattern
  tokens.forEach((tok, i) => {
    if (tok.text === "[") {
      if (depth) depth += 1;
      else if (i && tokens[i - 1].text === "-") depth = 1;
    } else if (tok.text === "]" && depth) depth -= 1;
    else if (tok.text === "*" && depth === 1) checkBound(tokens, i);
  });
}

function check(cypher) {
  if (typeof cypher !== "string" || !cypher.trim()) throw new Rejected("invalid_input", "cypher must not be empty.");
  if (cypher.length > MAX_CHARS) throw new Rejected("invalid_input", `cypher is longer than ${MAX_CHARS} characters.`);
  const tokens = tokenize(cypher);
  tokens.forEach((tok, i) => {
    const prev = i ? tokens[i - 1].text : "";
    if (tok.kind === "word") {
      const word = tok.text.toUpperCase();
      if (prev === "." || prev === "$") return; // a property or a parameter, not a clause
      if (FORBIDDEN.has(word)) throw reject(`${word} is not allowed: queries are read-only.`);
      const next = i + 1 < tokens.length ? tokens[i + 1].text.toUpperCase() : "";
      if (word === "IN" && next === "TRANSACTIONS") throw reject("IN TRANSACTIONS is not allowed.");
    } else if (tok.text === ";" && tokens.slice(i + 1).some((t) => t.text !== ";")) {
      throw reject("Only one statement is allowed.");
    }
  });
  checkHops(tokens);
}

// ---------------------------------------------------------------- values
// The wire value of a node is {id, kind: "node", labels, properties}, of a relationship
// {id, kind: "relationship", type, start_node, end_node, properties}. The daemon returns a node or
// relationship as its properties map, with every `<name>_json` string decoded (graph/store.py
// `_plain`); so does this.

function plain(value) {
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === "object") {
    if (value.kind === "node" || value.kind === "relationship") return decode(value.properties || {});
    return decode(value);
  }
  return value;
}

function decode(props) {
  const out = {};
  for (const [key, value] of Object.entries(props)) {
    if (key.endsWith("_json") && typeof value === "string") {
      try {
        out[key.slice(0, -5)] = JSON.parse(value);
        continue;
      } catch {
        /* not JSON after all: keep it as stored */
      }
    }
    out[key] = plain(value);
  }
  return out;
}

// ---------------------------------------------------------------- the database

let db = null;
let isWasmTrap = () => false;

async function load() {
  const t0 = performance.now();
  let mod;
  try {
    mod = await import("./wasm/relate.js");
  } catch (e) {
    throw new Error(`the Relate WASM files are not in this site (${e.message || e})`);
  }
  try {
    ({ isWasmTrap } = await import("./wasm/trap.js"));
  } catch {
    /* the classifier is optional */
  }
  await mod.default();
  const [manifest, script] = await Promise.all([
    fetch("data/manifest.json").then((r) => r.json()),
    fetch("data/graph.cypher").then((r) => {
      if (!r.ok) throw new Error(`data/graph.cypher: HTTP ${r.status}`);
      return r.text();
    }),
  ]);
  db = new mod.RelateDb();
  for (const raw of db.executeScript(script)) {
    if (!raw.includes('"error":null')) {
      const env = JSON.parse(raw);
      if (env.error) throw new Error(`loading the graph failed: ${env.error}`);
    }
  }
  const one = (q) => JSON.parse(db.execute(q, null)).rows[0].c;
  const nodes = one("MATCH (n) RETURN count(n) AS c");
  const relationships = one("MATCH ()-[r]->() RETURN count(r) AS c");
  if (nodes !== manifest.counts.nodes || relationships !== manifest.counts.relationships) {
    throw new Error(
      `the loaded graph has ${nodes} nodes and ${relationships} relationships, expected ${manifest.counts.nodes} and ${manifest.counts.relationships}`,
    );
  }
  return { nodes, relationships, ms: Math.round(performance.now() - t0) };
}

function run(cypher, params) {
  check(cypher);
  if (params !== undefined && params !== null && (typeof params !== "object" || Array.isArray(params))) {
    throw new Rejected("invalid_input", "params must be a JSON object.");
  }
  const raw = db.execute(cypher, params && Object.keys(params).length ? JSON.stringify(params) : null);
  const env = JSON.parse(raw);
  if (env.error) {
    const first = String(env.error).split("\n")[0].slice(0, 300);
    throw new Rejected("invalid_input", `The query failed: ${first}`);
  }
  const columns = env.columns || [];
  const rows = (env.rows || []).slice(0, MAX_ROWS + 1).map((row) => columns.map((c) => plain(row[c])));
  return { columns, rows: rows.slice(0, MAX_ROWS), truncated: rows.length > MAX_ROWS };
}

self.onmessage = (event) => {
  const { id, cypher, params } = event.data;
  try {
    self.postMessage({ id, ok: true, result: run(cypher, params) });
  } catch (e) {
    if (e instanceof Rejected) {
      self.postMessage({ id, ok: false, error: { code: e.code, message: e.message } });
    } else {
      const dead = isWasmTrap(e);
      self.postMessage({
        id,
        ok: false,
        dead,
        error: { code: "invalid_input", message: `The query failed: ${String((e && e.message) || e).slice(0, 300)}` },
      });
    }
  }
};

load().then(
  (info) => self.postMessage({ type: "ready", version: VERSION, ...info }),
  (e) => self.postMessage({ type: "failed", reason: String((e && e.message) || e) }),
);
