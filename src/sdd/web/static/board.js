// Board: milestone picker, three columns, live moves over SSE, polling fallback, event ticker.
import { api } from "./api.js";
import { agentColor, h, inline } from "./dom.js";

const COLUMNS = [
  ["todo", "To do"],
  ["claimed", "In progress"],
  ["done", "Done"],
];
const POLL_MS = 5000;
const TICKER_MAX = 6;

export function mount(el, arg) {
  let milestone = arg || "";
  let previous = new Map(); // task id -> column, to find the cards that moved
  let timer = null;
  let live = false;
  let started = false;
  let closed = false;
  const events = [];

  const picker = h("select", { "aria-label": "Milestone" });
  const counts = h("div", { class: "counts" });
  const liveEl = h("span", { class: "live small muted" });
  const cols = h("div", { class: "cols" });
  const ticker = h("ul", { class: "ticker", "aria-label": "Recent events" });
  const err = h("div", { class: "err" });
  el.append(
    h("div", { class: "bar" }, h("h2", {}, "Board"), picker, counts, h("span", { class: "grow" }), liveEl),
    err,
    cols,
    ticker,
  );

  picker.addEventListener("change", () => {
    milestone = picker.value;
    previous = new Map();
    location.hash = `#board/${encodeURIComponent(milestone)}`;
  });

  function card(t, flash) {
    return h(
      "div",
      { class: `card${flash ? " flash" : ""}`, "data-task": t.id },
      h("div", {}, h("span", { class: "id" }, t.id), " ", inline(t.title)),
      h(
        "div",
        { class: "meta" },
        t.group ? h("span", { class: "tag" }, t.group) : null,
        t.claimed_by
          ? h("span", { class: "chip", style: `background:${agentColor(t.claimed_by)}` }, t.claimed_by)
          : null,
        t.status === "done" && t.completed_by && t.completed_by !== t.claimed_by
          ? h("span", { class: "tag" }, `done by ${t.completed_by}`)
          : null,
      ),
    );
  }

  function draw(data) {
    const now = new Map();
    const moved = new Set();
    for (const [key] of COLUMNS) {
      for (const t of data.columns[key] || []) {
        now.set(t.id, key);
        if (previous.size && previous.get(t.id) !== key) moved.add(t.id);
      }
    }
    previous = now;
    cols.replaceChildren(
      ...COLUMNS.map(([key, title]) => {
        const tasks = (data.columns[key] || []).map((t) => ({ ...t, status: key }));
        return h(
          "section",
          { class: "col", "aria-label": title },
          h("h3", {}, `${title} · ${tasks.length}`),
          tasks.map((t) => card(t, moved.has(t.id))),
        );
      }),
    );
    counts.replaceChildren(
      ...COLUMNS.map(([key, title]) =>
        h("span", {}, h("b", {}, String((data.columns[key] || []).length)), " ", h("span", { class: "muted small" }, title)),
      ),
    );
    for (const c of cols.querySelectorAll(".flash")) setTimeout(() => c.classList.remove("flash"), 1500);
  }

  async function refresh() {
    try {
      const data = await api.board(milestone || undefined);
      err.textContent = "";
      if (data.milestone && !milestone) milestone = data.milestone.id;
      if (data.milestone) picker.value = data.milestone.id;
      draw(data);
    } catch (e) {
      err.textContent = e.message;
    }
  }

  function note(type, d) {
    if (type === "graph_changed") return;
    const text =
      type === "task"
        ? `${d.id} ${d.status}${d.claimed_by ? ` by ${d.claimed_by}` : ""}`
        : type === "deviation"
          ? `${d.id} logged: ${d.title}`
          : `${d.id} ${d.status}`;
    events.unshift(`${new Date().toLocaleTimeString()}  ${text}`);
    events.length = Math.min(events.length, TICKER_MAX);
    ticker.replaceChildren(...events.map((e) => h("li", {}, e)));
  }

  function setLive(on) {
    // EventSource retries report an error each time; do not restart the poll timer for those
    if (on === live && started) return;
    started = true;
    live = on;
    liveEl.className = `live small muted${on ? " on" : ""}`;
    liveEl.textContent = on ? "live" : "polling";
    clearInterval(timer);
    timer = on ? null : setInterval(refresh, POLL_MS);
  }

  const stop = api.events(
    (type, d) => {
      note(type, d);
      if (type !== "deviation") refresh();
    },
    (on) => {
      if (closed) return;
      const was = live;
      setLive(on);
      if (on && !was) refresh();
    },
  );
  setLive(false);

  api
    .milestones()
    .then((list) => {
      picker.replaceChildren(
        ...list.map((m) => new Option(`${m.id} · ${m.title} (${m.done}/${m.total})`, m.id)),
      );
      if (milestone) picker.value = milestone;
    })
    .catch(() => {})
    .finally(refresh);

  return () => {
    closed = true;
    stop();
    clearInterval(timer);
  };
}
