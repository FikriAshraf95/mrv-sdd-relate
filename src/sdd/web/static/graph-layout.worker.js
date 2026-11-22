// Force layout for the 3D graph, off the main thread (M09.3). It receives the graph by message
// (typed arrays), runs d3-force-3d until the simulation cools and posts positions back.
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from "./vendor/d3-force-3d/index.js";

const BATCH = 4; // ticks between two posts
const COOL = 0.01; // alpha below which the layout is at rest
let run = 0;

// message: {run, n, edges: Uint32Array [s0, t0, s1, t1, ...], pos: Float32Array (3n, every node seeded),
//   warm (some nodes were already placed: start with low energy), reduced}. Every post echoes `run`.
self.onmessage = (e) => {
  const { run: id, n, edges, pos, warm, reduced } = e.data;
  const mine = ++run; // a newer message cancels this loop
  const nodes = Array.from({ length: n }, (_, i) => {
    const seeded = Number.isFinite(pos[3 * i]); // NaN would mean "place it yourself"
    return seeded ? { x: pos[3 * i], y: pos[3 * i + 1], z: pos[3 * i + 2] } : {};
  });
  const links = [];
  for (let i = 0; i < edges.length; i += 2) links.push({ source: edges[i], target: edges[i + 1] });
  const sim = forceSimulation(nodes, 3)
    .force("link", forceLink(links).distance(32).strength(0.5))
    .force("charge", forceManyBody().strength(-70).distanceMax(500))
    .force("collide", forceCollide(5))
    .force("center", forceCenter(0, 0, 0).strength(0.06))
    .alpha(warm ? 0.35 : 1) // a relayout of a known graph starts warm, so it moves little
    .alphaDecay(0.03)
    .stop();

  const post = (done) => {
    const out = new Float32Array(3 * n);
    nodes.forEach((p, i) => {
      out[3 * i] = p.x;
      out[3 * i + 1] = p.y;
      out[3 * i + 2] = p.z;
    });
    self.postMessage({ run: id, pos: out, done }, [out.buffer]);
  };

  if (reduced) {
    while (sim.alpha() >= COOL) sim.tick();
    post(true);
    return;
  }
  const step = () => {
    if (mine !== run) return;
    for (let i = 0; i < BATCH && sim.alpha() >= COOL; i++) sim.tick();
    const done = sim.alpha() < COOL;
    post(done);
    if (!done) setTimeout(step, 0);
  };
  step();
};
