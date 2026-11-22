// O2 measurement (SPEC-00 §8, M08.3): how fast does Relate's WASM build load the sample's exported
// graph, and what does a node look like on the wire? Run by hand, never by pytest:
//   docker run --rm -v <pkg>:/pkg:ro -v <site>/data:/data:ro -v <this dir>:/w:ro -w /w node:22-slim \
//     node measure.mjs /pkg /data
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [pkg, data] = process.argv.slice(2);
const mod = await import(pathToFileURL(`${pkg}/relate.js`).href);
const bytes = readFileSync(`${pkg}/relate_bg.wasm`);
const script = readFileSync(`${data}/graph.cypher`, "utf8");
const manifest = JSON.parse(readFileSync(`${data}/manifest.json`, "utf8"));

const ms = (t0) => Math.round(performance.now() - t0);
const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
const run = (db, q, p = null) => JSON.parse(db.execute(q, p));
const counts = (db) => ({
  nodes: run(db, "MATCH (n) RETURN count(n) AS c").rows[0].c,
  relationships: run(db, "MATCH ()-[r]->() RETURN count(r) AS c").rows[0].c,
});

const t0 = performance.now();
mod.initSync({ module: bytes });
console.log(`initSync (compile + instantiate 7 MB wasm): ${ms(t0)} ms`);
console.log("expected", manifest.counts);

const results = {};
for (const method of ["script", "lines"]) {
  const times = [];
  let last = null;
  for (let i = 0; i < 5; i++) {
    const db = new mod.RelateDb();
    const t = performance.now();
    let error = null;
    if (method === "script") {
      const envs = db.executeScript(script).map((e) => JSON.parse(e));
      error = envs.find((e) => e.error)?.error ?? null;
      last = { statements: envs.length };
    } else {
      const lines = script.split("\n").filter((l) => l.trim() && !l.startsWith("//"));
      for (const l of lines) {
        const env = run(db, l.trim().replace(/;$/, ""));
        if (env.error) {
          error = env.error;
          break;
        }
      }
      last = { statements: lines.length };
    }
    times.push(ms(t));
    last = { ...last, error, ...counts(db) };
    db.free();
  }
  results[method] = { median_ms: median(times), all_ms: times, ...last };
  console.log(method, JSON.stringify(results[method]));
}

// the wire shape of nodes and relationships
const db = new mod.RelateDb();
db.executeScript(script);
const show = (q) => console.log(q, "\n ", db.execute(q, null).slice(0, 900));
show("MATCH (m:Milestone)-[r:INCLUDES]->(t:Task) RETURN m, r, t LIMIT 1");
show("MATCH (n:Table {id: 'table:bookings'}) RETURN n.id AS id, labels(n) AS l, properties(n) AS p");
show("MATCH (d:Deviation) RETURN d.id AS id LIMIT 2");
show("MATCH (f:File) RETURN f.id AS id LIMIT 0");
show("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC LIMIT 3");
show("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id", null);
console.log(db.execute("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id LIMIT 2", JSON.stringify({ ids: ["table:bookings", "D001"] })));
show("CREATE (x:Foo {id: 1}) RETURN x");
show("MATC (n)");
