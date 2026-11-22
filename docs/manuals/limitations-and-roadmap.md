# Limitations and roadmap

> What SDD Graph doesn't do (yet), stated plainly so you can decide whether it fits. Version 0.1.0, built for the Relate by Neo4j Hackathon.

## Known limitations

### Savings depend on your repo

- **Smaller repos save less.** On the Courtside sample, whose specs are short, the task packet is **61.2%** smaller than the Markdown an agent reads by hand, short of the 70% target ([D007](../deviations/D007-sample-s-graph-packet-is-61-smaller-than-the-markdown-rule.md)). On this repo, with longer specs, it's **71.9%**.
- **Unlinked tasks save nothing.** A task line that links no spec section gets the whole *Read first* list in full ([fix](how-to/link-tasks-to-sections.md)).
- Token counts are estimates (characters ÷ 4) unless you run `sdd bench --exact`. No live end-to-end run comparing two real agent sessions was done.

### Single machine, single writer

- **One daemon per repo, one machine.** Relate is a single-process engine, so exactly one process writes a store. Agents elsewhere reach it through a tunnel or private network with a token ([Remote access](how-to/token-and-remote-access.md)). There is no clustering and no multi-repo daemon, and no queries across stores.
- **No user accounts.** Security is a loopback bind, an optional shared bearer token, and Host/Origin checks. Agent names are self-declared: any client with access can act as any agent name.
- **Claims expire by time, not heartbeat.** A dead agent's claim is free after 2 h, or immediately with a forced release.

### The static demo's scope

- On GitHub Pages, **only the Query tab runs real Cypher**, in Relate's WebAssembly build. The Board, Graph, Impact and Explain views use answers precomputed by `sdd site` for every table, feature, file and section ([D008](../deviations/D008-static-demo-runs-only-the-query-tab-in-relate-wasm-the-other.md)). Targets outside that set aren't available there.
- **Without WebAssembly**, the Query tab still runs its six example queries from precomputed answers, but not your own Cypher ([D009](../deviations/D009-without-wasm-the-query-tab-still-runs-the-six-example.md)). The footer says which mode you're in.
- The static demo doesn't update live. Its *Replay* button plays a recorded sprint.

### Parsing

- It reads one SDD layout (specs, milestones with checkbox tasks, deviation files), configurable by globs but not by grammar. Other formats (ADR tools, issue trackers, Notion exports) become plain Docs at best.
- **No code symbols.** Files are nodes; functions, classes and call graphs aren't (agents grep well). File contents are never stored.
- **Tables come from the schema spec**, not from ORM models or migrations. `find_code(table=…)` matches `migrations`/`models` paths by name as a hint only.
- Section IDs come from heading numbers, so renumbering a spec changes them. References such as `SPEC-03 §4` then point at whatever now has that number, or show up as unresolved in `sdd doctor`. Add new sections at the end rather than renumbering.

### Engine limits worked around

- `relate-db` 1.2 has no per-query timeout or row cap, so the guard enforces 5 s, 100 rows and a memory cap itself, in a killable worker process, one query at a time ([D006](../deviations/D006-guarded-queries-run-in-a-killable-worker-process-with-a.md)).
- No map properties: maps are stored as JSON strings (`header_json`, `data_json`).
- `.rl` and JSON snapshots need the separate `relate` CLI; the Python package can't make them.
- The guard rejects `CALL`, so full-text indexes can't be queried from the Query tab.
- No schema migrations yet: a store built with another schema version is rebuilt with `sdd sync --reset`.

### Platform

- Python 3.13 only, and a `relate-db` wheel must exist for your platform (none for musl/Alpine). Docker covers the rest.
- Inside Docker on Windows or macOS, file watching polls: Markdown every second, code every 10 s or more (minutes on very large trees).
- Not on PyPI yet: install from git.

## Roadmap

Planned for the release milestone (M99):

- A security sweep against the security spec, and open deviations folded into the specs or kept as documented limitations.
- Final committed stores for the sample and this repo, a `v1.0.0` tag.
- Browsing a store with Neo4j Browser through `relate serve --bolt` (bonus, not yet verified).

Ideas beyond v1, not scheduled:

- **Relate's Markdown vault store**, once released, in place of SDD Graph's own Markdown sync.
- **Vector search** over section text, to find related sections no link connects.
- **A global lessons store**: deviations and completion notes copied across projects, so one repo's lessons reach the next.
- Packaging on PyPI (`uvx relate-sdd`), and schema migrations instead of rebuilds.

Out of scope by design: replacing Markdown, editing spec prose through tools, multi-user hosting with accounts, or any public write access.

Found a limitation not listed here? It may be a bug, or an unlogged deviation, which counts as one. Open an issue on the repository.
