// The 3D graph (M09.3): three.js scene, nodes as one instanced mesh, edges as line segments, the
// force layout in graph-layout.worker.js. Renders on demand: a frame only while the layout moves,
// the camera damps or a fly-to runs. Labels are DOM (CSS2DRenderer): hover, selection and hubs.
//
// create(host, {onSelect, onExpand}) -> view; throws when WebGL is unavailable (graph.js then
// opens the 2D view). A view has set(nodes, edges), setShown(labels), search(q), select(id),
// reset(), restyle(), destroy().
import {
  AmbientLight,
  BufferAttribute,
  BufferGeometry,
  Color,
  DirectionalLight,
  Fog,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  MeshLambertMaterial,
  PerspectiveCamera,
  Scene,
  SphereGeometry,
  Vector3,
  WebGLRenderer,
} from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "./vendor/three/CSS2DRenderer.js";
import { LABELS, css, h, labelColor } from "./dom.js";

const HUBS = 6; // labels kept on the highest-degree nodes
const CLICK_PX = 5;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function create(host, cb) {
  const renderer = new WebGLRenderer({ antialias: true }); // throws without WebGL
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const labelRenderer = new CSS2DRenderer({ element: h("div", { class: "labels" }) });
  const scene = new Scene();
  const camera = new PerspectiveCamera(55, 1, 1, 4000);
  scene.add(new AmbientLight(0xffffff, 1.6));
  const sun = new DirectionalLight(0xffffff, 2.2);
  sun.position.set(1, 1.4, 1.2);
  scene.add(sun);
  host.append(renderer.domElement, labelRenderer.domElement);
  renderer.domElement.style.position = "absolute";
  renderer.domElement.style.inset = "0";

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.autoRotateSpeed = 0.6;
  let rotateTimer = 0;
  // a slow turn until the first interaction or 20 s, so an untouched tab stops rendering
  function spin(on) {
    clearTimeout(rotateTimer);
    controls.autoRotate = on && !reduced();
    if (controls.autoRotate) rotateTimer = setTimeout(() => spin(false), 20000);
  }
  spin(true);
  controls.zoomSpeed = 0.8;

  // ---- state
  let nodes = []; // {id, label, title}
  let index = new Map(); // id -> i
  let edgePairs = []; // [s, t] indices
  let degree = [];
  let pos = new Float32Array(0);
  let shown = null; // Set of labels, null = all
  let hidden = []; // per node
  let hover = -1;
  let selected = -1;
  let hits = new Set();
  let mesh = null;
  let lines = null;
  let hiLines = null;
  let neighbours = new Map(); // i -> Set of edge numbers
  let fitted = false;
  let layoutRunning = false;
  let run = 0; // layout run the worker answers for; older batches are dropped
  let sizeScale = 1; // shrinks as the graph grows, so a dense graph does not turn into a ball
  const radiusOf = (degree) => sizeScale * (2 + 1.5 * Math.log2(1 + degree));
  let pendingFly = ""; // a search or deep link asked to fly to this ID while the layout was still moving
  let tween = null;
  let frameId = 0;
  let dead = false;
  const labelObjs = new Map(); // i -> CSS2DObject
  const dummy = new Matrix4();
  const tmp = new Vector3();
  const colour = new Color();

  const worker = new Worker(new URL("graph-layout.worker.js", import.meta.url), { type: "module" });
  worker.onmessage = (e) => {
    if (dead || e.data.run !== run) return; // a stale batch from before the last set()
    pos = e.data.pos;
    layoutRunning = !e.data.done;
    if (e.data.done && pendingFly) {
      const i = index.get(pendingFly);
      pendingFly = "";
      if (i !== undefined) focusOn(i); // now that the nodes are where they will stay
    } else if (!fitted && (e.data.done || reduced())) fit();
    else if (!fitted && nodes.length > 40 && !tween) fit(true);
    writeNodes();
    writeEdges();
    syncLabels();
    kick();
  };

  function kick() {
    if (!frameId && !dead) frameId = requestAnimationFrame(frame);
  }

  function frame(now) {
    frameId = 0;
    if (dead) return;
    let busy = layoutRunning;
    if (tween) {
      const k = Math.min(1, (now - tween.t0) / tween.ms);
      const e = 1 - (1 - k) ** 3;
      camera.position.lerpVectors(tween.fromPos, tween.toPos, e);
      controls.target.lerpVectors(tween.fromTarget, tween.toTarget, e);
      if (k >= 1) tween = null;
      busy = true;
    }
    if (controls.update()) busy = true;
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
    if (busy) kick();
  }
  controls.addEventListener("change", kick);
  controls.addEventListener("start", () => {
    spin(false); // first interaction ends the slow turn
    pendingFly = "";
    fitted = true; // and the layout stops re-framing the camera
    tween = null;
  });

  function resize() {
    const w = Math.max(1, host.clientWidth);
    const hgt = Math.max(1, host.clientHeight);
    renderer.setSize(w, hgt, false);
    renderer.domElement.style.width = `${w}px`;
    renderer.domElement.style.height = `${hgt}px`;
    labelRenderer.setSize(w, hgt);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
    kick();
  }
  const observer = new ResizeObserver(resize);
  // a tab that was hidden may have a frame request that never ran: draw again when it is shown
  const onVisible = () => {
    if (document.hidden) return;
    cancelAnimationFrame(frameId);
    frameId = 0;
    kick();
  };
  document.addEventListener("visibilitychange", onVisible);
  observer.observe(host);

  // ---- camera
  function bounds() {
    let n = 0;
    const c = new Vector3();
    for (let i = 0; i < nodes.length; i++) {
      if (hidden[i]) continue;
      c.x += pos[3 * i];
      c.y += pos[3 * i + 1];
      c.z += pos[3 * i + 2];
      n++;
    }
    if (!n) return { c, r: 60 };
    c.divideScalar(n);
    // the 85th percentile, so a few far-flung leaves do not shrink the whole graph
    const d = [];
    for (let i = 0; i < nodes.length; i++) {
      if (!hidden[i]) d.push(tmp.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]).distanceTo(c));
    }
    d.sort((a, b) => a - b);
    return { c, r: Math.max(20, d[Math.floor(d.length * 0.85)] * 1.1) };
  }

  function flyTo(target, distance, dir = null) {
    fitted = true; // an explicit camera move wins over the layout's auto-fit
    const d = dir || tmp.copy(camera.position).sub(controls.target).normalize().clone();
    const toPos = target.clone().add(d.multiplyScalar(distance));
    if (reduced()) {
      camera.position.copy(toPos);
      controls.target.copy(target);
      controls.update();
      kick();
      return;
    }
    tween = {
      t0: performance.now(),
      ms: 650,
      fromPos: camera.position.clone(),
      toPos,
      fromTarget: controls.target.clone(),
      toTarget: target.clone(),
    };
    kick();
  }

  function fit(soft = false) {
    if (!nodes.length) return;
    const { c, r } = bounds();
    const distance = (r / Math.sin((camera.fov * Math.PI) / 360)) * 0.8;
    const dir = new Vector3(0.35, 0.25, 1).normalize();
    if (soft) {
      // while the layout is still spreading: follow it without animating
      camera.position.copy(c).add(dir.multiplyScalar(distance));
      controls.target.copy(c);
    } else {
      fitted = true;
      camera.position.copy(c).add(dir.multiplyScalar(distance));
      controls.target.copy(c);
    }
    camera.far = Math.max(4000, distance * 6);
    camera.updateProjectionMatrix();
    scene.fog = new Fog(css("--bg-1"), distance * 0.9, distance * 2.6);
    controls.update();
  }

  // ---- scene content
  function writeNodes() {
    if (!mesh) return;
    const near = hover >= 0 ? neighbourSet(hover) : null;
    for (let i = 0; i < nodes.length; i++) {
      let s = hidden[i] ? 0 : radiusOf(degree[i]);
      if (i === selected || hits.has(i)) s *= 1.5;
      else if (i === hover) s *= 1.35;
      else if (near && near.has(i)) s *= 1.15;
      dummy.makeScale(s, s, s).setPosition(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]);
      mesh.setMatrixAt(i, dummy);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }

  function paintNodes() {
    if (!mesh) return;
    const accent = new Color(css("--accent"));
    for (let i = 0; i < nodes.length; i++) {
      colour.set(labelColor(nodes[i].label));
      if (i === selected || hits.has(i)) colour.lerp(accent, 0.55).offsetHSL(0, 0, 0.08);
      mesh.setColorAt(i, colour);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }

  const isHidden = (n) => !!shown && LABELS.includes(n.label) && !shown.has(n.label);

  function edgeVisible(k) {
    const [s, t] = edgePairs[k];
    return !hidden[s] && !hidden[t];
  }

  function writeEdges() {
    if (!lines) return;
    const a = lines.geometry.attributes.position;
    for (let k = 0; k < edgePairs.length; k++) {
      const [s, t] = edgePairs[k];
      const on = edgeVisible(k);
      for (let j = 0; j < 3; j++) {
        a.array[6 * k + j] = on ? pos[3 * s + j] : 0;
        a.array[6 * k + 3 + j] = on ? pos[3 * t + j] : 0;
      }
    }
    a.needsUpdate = true;
    writeHighlight();
  }

  // the edges of the hovered or selected node, in the accent colour
  function writeHighlight() {
    if (!hiLines) return;
    const focus = hover >= 0 ? hover : selected;
    const list = focus >= 0 ? [...(neighbours.get(focus) || [])].filter(edgeVisible) : [];
    const attr = hiLines.geometry.attributes.position;
    list.forEach((k, n) => {
      const [s, t] = edgePairs[k];
      for (let j = 0; j < 3; j++) {
        attr.array[6 * n + j] = pos[3 * s + j];
        attr.array[6 * n + 3 + j] = pos[3 * t + j];
      }
    });
    attr.needsUpdate = true;
    hiLines.geometry.setDrawRange(0, list.length * 2); // one buffer, sized once in set()
  }

  function neighbourSet(i) {
    const out = new Set();
    for (const k of neighbours.get(i) || []) {
      const [s, t] = edgePairs[k];
      out.add(s === i ? t : s);
    }
    return out;
  }

  function syncLabels() {
    const want = new Set();
    const order = nodes.map((_, i) => i).filter((i) => !hidden[i]);
    order.sort((a, b) => degree[b] - degree[a]).slice(0, HUBS).forEach((i) => want.add(i));
    for (const i of [hover, selected]) if (i >= 0 && !hidden[i]) want.add(i);
    for (const [i, obj] of labelObjs) {
      if (!want.has(i)) {
        scene.remove(obj);
        obj.element.remove();
        labelObjs.delete(i);
      }
    }
    for (const i of want) {
      let obj = labelObjs.get(i);
      if (!obj) {
        obj = new CSS2DObject(h("div", { class: "glabel" }, nodes[i].id.length > 24 ? `${nodes[i].id.slice(0, 22)}…` : nodes[i].id));
        labelObjs.set(i, obj);
        scene.add(obj);
      }
      obj.element.classList.toggle("on", i === hover || i === selected);
      obj.position.set(pos[3 * i], pos[3 * i + 1] + radiusOf(degree[i]) + 3, pos[3 * i + 2]);
    }
  }

  function dispose() {
    for (const obj of labelObjs.values()) {
      scene.remove(obj);
      obj.element.remove();
    }
    labelObjs.clear();
    for (const o of [mesh, lines, hiLines]) {
      if (!o) continue;
      scene.remove(o);
      o.geometry.dispose();
      o.material.dispose();
      if (o.dispose) o.dispose();
    }
    mesh = lines = hiLines = null;
  }

  function set(newNodes, newEdges) {
    const old = new Map();
    // positions are reused (a warm re-layout) only when the last layout had settled; an unfinished one
    // is still a seed sphere, and starting from it would leave the graph squeezed together
    if (!layoutRunning) nodes.forEach((n, i) => old.set(n.id, [pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]]));
    const selectedId = selected >= 0 ? nodes[selected].id : null;
    dispose();
    nodes = newNodes.map((n) => ({ id: n.id, label: n.label, title: n.title }));
    index = new Map(nodes.map((n, i) => [n.id, i]));
    edgePairs = [];
    const seen = new Set();
    for (const e of newEdges) {
      const s = index.get(e.source);
      const t = index.get(e.target);
      const key = `${s}|${t}|${e.type}`;
      if (s === undefined || t === undefined || seen.has(key)) continue;
      seen.add(key);
      edgePairs.push([s, t]);
    }
    sizeScale = Math.min(1, Math.cbrt(300 / Math.max(1, nodes.length))); // 1 up to 300 nodes, 0.53 at 2 000
    degree = new Array(nodes.length).fill(0);
    neighbours = new Map();
    edgePairs.forEach(([s, t], k) => {
      degree[s]++;
      degree[t]++;
      for (const i of [s, t]) {
        if (!neighbours.has(i)) neighbours.set(i, new Set());
        neighbours.get(i).add(k);
      }
    });
    pos = new Float32Array(3 * nodes.length).fill(Number.NaN);
    nodes.forEach((n, i) => {
      const p = old.get(n.id);
      if (p) pos.set(p, 3 * i);
    });
    hover = -1;
    selected = selectedId ? (index.get(selectedId) ?? -1) : -1;
    hits = new Set();
    hidden = nodes.map(isHidden);

    mesh = new InstancedMesh(new SphereGeometry(1, 14, 10), new MeshLambertMaterial({ color: 0xffffff }), Math.max(1, nodes.length));
    mesh.count = nodes.length;
    mesh.frustumCulled = false;
    scene.add(mesh);
    const lineGeo = new BufferGeometry();
    lineGeo.setAttribute("position", new BufferAttribute(new Float32Array(edgePairs.length * 6), 3));
    lines = new LineSegments(lineGeo, new LineBasicMaterial({ color: css("--fg-2"), transparent: true, opacity: 0.3, depthWrite: false }));
    lines.frustumCulled = false;
    scene.add(lines);
    const hiGeo = new BufferGeometry();
    hiGeo.setAttribute("position", new BufferAttribute(new Float32Array(edgePairs.length * 6), 3));
    hiLines = new LineSegments(hiGeo, new LineBasicMaterial({ color: css("--accent"), transparent: true, opacity: 0.9 }));
    hiLines.frustumCulled = false;
    scene.add(hiLines);
    paintNodes();

    // Unseeded nodes: next to an already placed neighbour (an expanded node's new neighbours appear
    // around it), else at a deterministic spot by index, so two loads look the same.
    const placed = nodes.map((n) => old.has(n.id));
    const warm = placed.some(Boolean);
    for (let i = 0; i < nodes.length; i++) {
      if (placed[i]) continue;
      const near = [...(neighbours.get(i) || [])].map((k) => edgePairs[k].find((x) => x !== i)).find((j) => placed[j]);
      const k = i + 0.5;
      const phi = Math.acos(1 - (2 * k) / nodes.length);
      const theta = Math.PI * (1 + Math.sqrt(5)) * k;
      if (near !== undefined) {
        pos.set(
          [pos[3 * near] + 12 * Math.cos(theta) * Math.sin(phi), pos[3 * near + 1] + 12 * Math.sin(theta) * Math.sin(phi), pos[3 * near + 2] + 12 * Math.cos(phi)],
          3 * i,
        );
      } else {
        const r = 30 + 4 * Math.cbrt(nodes.length);
        pos.set([r * Math.cos(theta) * Math.sin(phi), r * Math.sin(theta) * Math.sin(phi), r * Math.cos(phi)], 3 * i);
      }
    }
    writeNodes();
    writeEdges();
    syncLabels();
    layoutRunning = nodes.length > 0;
    run++;
    const flat = Uint32Array.from(edgePairs.flat());
    worker.postMessage({ run, n: nodes.length, edges: flat, pos: new Float32Array(pos), warm, reduced: reduced() });
    kick();
  }

  // ---- interaction
  function pick(clientX, clientY) {
    const box = renderer.domElement.getBoundingClientRect();
    const x = clientX - box.left;
    const y = clientY - box.top;
    let best = -1;
    let bestScore = Infinity;
    for (let i = 0; i < nodes.length; i++) {
      if (hidden[i]) continue;
      tmp.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]).project(camera);
      if (tmp.z > 1) continue;
      const sx = ((tmp.x + 1) / 2) * box.width;
      const sy = ((1 - tmp.y) / 2) * box.height;
      const d = Math.hypot(sx - x, sy - y);
      const dist = camera.position.distanceTo(tmp.set(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]));
      const px = (radiusOf(degree[i]) / dist) * (box.height / (2 * Math.tan((camera.fov * Math.PI) / 360)));
      if (d > Math.max(8, px + 3)) continue;
      const score = d + dist * 0.01; // nearest to the pointer, the nearer node on a tie
      if (score < bestScore) {
        bestScore = score;
        best = i;
      }
    }
    return best;
  }

  function setHover(i) {
    if (i === hover) return;
    hover = i;
    renderer.domElement.style.cursor = i >= 0 ? "pointer" : "";
    writeNodes();
    writeHighlight();
    syncLabels();
    kick();
  }

  let down = null;
  let moving = 0;
  const dom = renderer.domElement;
  dom.addEventListener("pointerdown", (e) => {
    down = { x: e.clientX, y: e.clientY, t: performance.now() };
  });
  dom.addEventListener("pointermove", (e) => {
    if (e.buttons || moving) return; // orbiting
    moving = requestAnimationFrame(() => {
      moving = 0;
      setHover(pick(e.clientX, e.clientY));
    });
  });
  dom.addEventListener("pointerleave", () => setHover(-1));
  // click selects; a second click on the same node within 350 ms (a double tap too, since
  // `dblclick` does not fire on touch) flies to it and expands its neighbours
  let lastTap = { i: -1, t: 0 };
  dom.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > CLICK_PX) return;
    down = null;
    const i = pick(e.clientX, e.clientY);
    if (i < 0) return;
    const now = performance.now();
    const again = i === lastTap.i && now - lastTap.t < 350;
    lastTap = again ? { i: -1, t: 0 } : { i, t: now };
    select(nodes[i].id);
    cb.onSelect(nodes[i].id);
    if (again) {
      focusOn(i);
      cb.onExpand(nodes[i].id);
    }
  });

  function focusOn(i) {
    const target = new Vector3(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]);
    // approach from outside the cloud (centroid -> node), so the node is not buried in its neighbours
    const out = target.clone().sub(bounds().c);
    const dir = out.lengthSq() > 1 ? out.normalize() : null;
    flyTo(target, 90 + 5 * radiusOf(degree[i]), dir);
  }

  function select(id) {
    selected = index.has(id) ? index.get(id) : -1;
    paintNodes();
    writeNodes();
    writeHighlight();
    syncLabels();
    kick();
  }

  // exact ID first (then only that node is marked), else every title or ID match; flies to the best
  function search(q) {
    q = q.trim().toLowerCase();
    hits = new Set();
    const exact = q ? nodes.findIndex((n, i) => !hidden[i] && n.id.toLowerCase() === q) : -1;
    if (exact >= 0) hits.add(exact);
    else if (q) {
      nodes.forEach((n, i) => {
        if (!hidden[i] && (n.id.toLowerCase().includes(q) || String(n.title ?? "").toLowerCase().includes(q))) hits.add(i);
      });
    }
    paintNodes();
    writeNodes();
    if (hits.size) {
      spin(false);
      const best = exact >= 0 ? exact : [...hits].sort((a, b) => degree[b] - degree[a])[0];
      if (layoutRunning) pendingFly = nodes[best].id;
      else focusOn(best);
    }
    kick();
    return hits.size;
  }

  function setShown(labels) {
    shown = labels;
    hidden = nodes.map(isHidden);
    writeNodes();
    writeEdges();
    syncLabels();
    kick();
  }

  function reset() {
    hits = new Set();
    hover = selected = -1;
    paintNodes();
    writeNodes();
    writeHighlight();
    syncLabels();
    spin(true);
    fitted = false;
    fit();
    kick();
  }

  function restyle() {
    renderer.setClearColor(new Color(css("--bg-1")));
    if (lines) lines.material.color.set(css("--fg-2"));
    if (hiLines) hiLines.material.color.set(css("--accent"));
    if (scene.fog) scene.fog.color.set(css("--bg-1"));
    paintNodes();
    kick();
  }
  restyle();
  resize();

  function destroy() {
    dead = true;
    clearTimeout(rotateTimer);
    cancelAnimationFrame(frameId);
    cancelAnimationFrame(moving);
    observer.disconnect();
    document.removeEventListener("visibilitychange", onVisible);
    worker.terminate();
    controls.dispose();
    dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
    labelRenderer.domElement.remove();
  }

  return { set, setShown, search, select, reset, restyle, destroy, count: () => ({ nodes: nodes.length, edges: edgePairs.length }) };
}
