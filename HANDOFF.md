# HANDOFF — Relate SDD Graph (Relate by Neo4j Hackathon)

> Context brief carried over from a planning conversation in Claude (claude.ai), 2026-11-17.
> Purpose: give Claude Code everything needed to write the project specs and milestones.
> Facts marked **[verified]** were checked against the Relate repo (v1.0.3) / docs / Devpost page. Anything else is a design decision or open question.

---

## 1. The hackathon

- **Event:** Relate by Neo4j Hackathon — theme "Context, connected." Online, month-long, celebrates the launch of Relate at NODES 2026. https://relate.devpost.com/
- **Deadline:** **Dec 11, 2026, 6:00 pm PST** = **Dec 12, 10:00 am Malaysia time (UTC+8)**.
- **Challenge:** build something showing how connected data helps agents, apps, or people find and use the relationships that matter. New projects or extensions are both fine.
- **Submission requirements:**
  - Public GitHub repo, README covering setup and use.
  - GitHub topic **`relate`** (required); `relate-neo4j-hackathon` recommended.
  - **Persistent Relate store** committed (directory or single file) so judges can inspect it. In-memory doesn't count.
  - **Working code with Relate actually running.** Prompt-only or AI-generated text entries without a running Relate integration are rejected.
  - Project description: the use case and what connects to what.
  - 1–2 minute demo video.
  - README must state **how Relate is used (in-memory / directory / single file) and why**. Devpost provides a README template.
- **Judging:** Relate and connected context 30 · Functionality and completeness 25 · Usefulness 20 · Documentation and reproducibility 15 · Creativity 10.
- **Judges (all Neo4j):** Michael Hunger (author of the ideas list github.com/jexp/relate-ideas), Andreas Kollegger, William Lyon, Oskar Hane, Yaru Lin, Kate Smith, Jennifer Reif, Stephen Chin.
- **Prizes:** Mac Studio / Mac mini / Mac mini (one per winning entry).

---

## 2. The user's current workflow (what we're upgrading)

The user practices **Spec-Driven Development (SDD)** and ships production projects with it:

- Many spec files and milestone/sprint files per project, cross-linked to each other.
- An AI agent reads the main milestone file / `CLAUDE.md` to start building, and marks items complete there when done.
- For later milestones the agent re-reads spec, **deviation** and **memory** files to continue.
- **Orchestrator–worker pattern:** an Opus orchestrator launches one or more Sonnet subagents in parallel.

**Pain points:**
1. **Token bloat / re-reading.** Agents re-read whole Markdown files every session just to find what changed.
2. **Parallel write collisions.** Several subagents updating `CLAUDE.md` / milestone checklists risk overwriting each other.
3. **Lost lineage.** Hard to see which earlier deviation changed a spec that a later task depends on.

Goal: **Markdown stays the human source of truth.** A Relate graph gives agents a live, queryable, always-current view, so they query exactly what they need instead of re-reading files.

---

## 3. Prior art (position against these in the README)

- **Spec-Driven Development** is the established name. Tools: **GitHub Spec Kit** (Specify → Plan → Tasks → Implement; spec files, but agents still read them as text) and **Kiro** (AWS, 3-phase spec workflow). CLAUDE.md files used as lightweight specs.
- **Beads** (Steve Yegge, github.com/steveyegge/beads, ~24k stars): git-backed **graph issue tracker for AI agents** with dependency types (blocks, related, parent-child, discovered-from) and ready-work detection. It *replaces* Markdown plans. It does **not** model specs or deviations.
- **Gap we fill:** specs + deviations + tasks + milestones + code in **one connected graph**, with Markdown kept as source of truth, so the agent context for one task is a graph traversal, not a file re-read.
- **Pitch:** "Spec Kit-style specs plus Beads-style task tracking, joined in one Relate graph, so agents follow how specs, deviations and code connect instead of re-reading files."
- Related entries in jexp/relate-ideas: *Obsidian/VFS Native*, *Agent Handoff Object*, *Skills as Graphs*, *Graph-Native Agent Memory*. None covers SDD explicitly.

---

## 4. Relate facts **[verified]** (repo README + docs/limitations.md, v1.0.3)

- Embedded property-graph engine in Rust. Self-description: "closer to SQLite than to a clustered graph server." Apache-2.0. Cypher (current dialect, openCypher TCK floor).
- **Install:** CLI `curl -sSfL https://relatedb.ai/install.sh | bash`; Python `pip install relate-db` (import is `import relate`); also Node, WASM, Rust, Java, Go, Swift.
- **Python API:**
  ```python
  import relate
  db = relate.connect(".sdd/graph")      # dir, .rl file, or ":memory:"
  db.execute("CREATE (p:Person {name: $name})", {"name": "Alice"})
  for row in db.execute("MATCH (p:Person) RETURN p.name"):
      print(row["p.name"])
  ```
  Also `execute_arrow()` for pandas/Polars. Spec: `docs/api/python/` in the repo.
- **Storage modes:** in-memory; **directory (default)** = WAL + Parquet shards; directory + `--snapshot-format json` = readable `graph.json`; **single `.rl` file**. `relate clone SRC DEST` converts directory ↔ `.rl`. Durability modes: `full` (default), `everysecond`, `snapshot`.
- **⚠ Single-process engine.** A store is used from **one process**. It is not multi-process or multi-writer. Threads in that process may read concurrently; overlapping writers get `write-write conflict` (exit code 5), with **no automatic retry**.
- **Read-only live follow:** `--read-only=live` (Rust: `OpenMode::Follow`) **follows a native directory store's WAL while another process writes it.** Enables live dashboards and inspection alongside the writer.
- **⚠ No cross-database queries.** One graph per statement; `.attach`/`.use` multi-DB is withdrawn.
- **Transactions:** single-level explicit (begin/commit/rollback); no nesting. `CALL { … } IN TRANSACTIONS` for batching.
- **Vector search:** `vector()` properties, `CREATE VECTOR INDEX`, `SEARCH` clause with pre-filtering, hybrid vector + full-text.
- **Agent ergonomics:** `--json`, `--jsonl`, `--mode envelope`; machine-readable errors `{"error":{code,exit_code,kind,message,retryable}}`; exit codes 2 usage, 6 rejected statement, 5 conflict/locked, 1 runtime. Under an agent harness, a 100-row cap is announced in-band (`--max-rows N` to change).
- **Agent skill:** `relate skill install --agent claude-code`.
- **Server:** `relate serve --database ./g --bolt 7687 --http 7474 --mcp 7475` (one process, one store, token auth, binds loopback). `relate serve --mcp stdio --database ./g --read-only` for read-only agent access.
- **Extensions:** `fs-to-graph` (directory tree → `(:File)` + `[:CONTAINS]`, full-text) and **`git-to-graph`** (commits, parents, changed paths). Can link tasks to the commits that completed them. Custom extensions: `relate extension init <name> --lang py`.
- **⚠ Obsidian / Markdown-vault store is NOT released.** `docs/guides/obsidian-vault.md` says it's in development on branch `feat/markdown-vault-store` (ADR-0406), and it's absent from the CHANGELOG. **Do not depend on it.** Write our own Markdown → graph sync and mention the vault feature as future work.
- Docs: https://relatedb.ai/ · repo https://github.com/relatedb/relate (`docs/limitations.md`, `docs/guides/`, `docs/api/python/`, `docs/adr/`).

---

## 5. Design decisions so far

### Architecture
```
specs/*.md, milestones/*.md      ← humans edit (source of truth)
        │  file watcher → hash → re-parse only changed files
        ▼
  sdd daemon  (ONE Python process; embeds Relate; sole owner of .sdd/graph/)
        │  MCP over localhost HTTP  (+ thin `sdd` CLI)
        ▼
  Opus orchestrator  +  N Sonnet subagents  (all Claude Code sessions share one server)
```

- **Language/packaging:** Python package (pip / `uvx` installable), not a compiled exe. Uses `relate-db` in-process.
- **One daemon owns the store.** Required by Relate's single-process rule. All writes are serialized through it, with retry on conflict.
- **MCP transport = HTTP on localhost, not stdio.** stdio would start one server per Claude Code session, so several processes would fight over one store. A project `.mcp.json` points Claude Code at the daemon.
- **Custom task-level MCP tools, not raw `relate serve --mcp`.** Guardrails: no double-claims, dependencies enforced.
- **Directory store** at `.sdd/graph/` so `--read-only=live` can follow it. For submission, also commit a `.rl` copy made with `relate clone` and/or a JSON-codec snapshot for readability.
- **Per-project store** (travels with the repo). Optional **global lessons store** (`~/.sdd/lessons`) holding *copies* of promoted lessons (no cross-DB queries possible). This is a stretch goal.

### Draft graph schema (to refine in specs)
**Planning layer (from Markdown):**
- Nodes: `Milestone {id, title, status, order}`, `Task {id, title, status, assigned_agent, acceptance_criteria}`, `Spec {id, path, content_hash, summary, last_synced}` (possibly `SpecSection` nodes per heading for fine-grained context), `Deviation {id, reason, impact_summary, created_at}`, `Agent`, `Session`, `Lesson` (stretch).
- Relationships: `(Milestone)-[:DEPENDS_ON]->(Milestone)`, `(Milestone)-[:INCLUDES]->(Task)`, `(Task)-[:BLOCKED_BY]->(Task)`, `(Task)-[:GOVERNED_BY]->(Spec|SpecSection)`, `(Deviation)-[:AMENDS]->(Spec|SpecSection)`, `(Deviation)-[:RAISED_IN]->(Task)`, `(Agent)-[:CLAIMED]->(Task)`.

**Codebase layer (see §5a):** `Folder`, `File`, `Commit`, `Table`, `Column`, `Feature`, `Domain`, linked to the planning layer. Full list in §5a.

### 5a. Codebase context layer (steps 1–4 in scope; step 5 deferred)

Decided 2026-11-19. Store the **codebase structure and intent** in the graph, not just Markdown content, so agents find code by relationship and the spec ↔ code ↔ table chain gives a strong "why a graph" demo.

**Guiding principle:** the graph stores **connections and intent that grep can't find** (which feature owns which file, which spec governs which table, why something changed). It does **not** mirror code contents; agents still read files and grep for details.

**In scope:**

1. **Files and folders.** `(Folder)-[:CONTAINS]->(Folder|File)`, `File {path, language, content_hash, size, last_synced}`. Relate's first-party **`fs-to-graph`** extension already produces `(:File)` + `[:CONTAINS]` with full-text over names and contents. Evaluate reusing it vs. our own walker (must respect `.gitignore`, skip `node_modules`/build output, and fit our sync model).
2. **Git history.** `Commit {sha, message, author, timestamp}`, `(Commit)-[:PARENT]->(Commit)`, `(Commit)-[:CHANGED]->(File)`, `(Commit)-[:COMPLETES]->(Task)` (from commit-message convention, e.g. `[T-012]`, or set by `complete_task`). Relate's **`git-to-graph`** extension covers commits, parents and changed paths. Evaluate reuse. Incremental: only commits since the last synced sha.
3. **Database tables.** Parse schema/migration files into `Table {name, source_file}`, `Column {name, type, nullable, pk}`, `(Table)-[:HAS_COLUMN]->(Column)`, `(Column)-[:REFERENCES]->(Column)` / `(Table)-[:REFERENCES]->(Table)` for foreign keys, `(File)-[:DEFINES_TABLE]->(Table)`. **Ask the user which schema sources they use** (raw SQL migrations, Prisma, Drizzle, Django/SQLAlchemy models, etc.). Support one or two well for v1 via a pluggable parser interface.
4. **Features and domains (human-declared).** `Feature {id, name}`, `Domain {id, name}`, `(Feature)-[:BELONGS_TO]->(Domain)`, `(Feature)-[:SPECIFIED_BY]->(Spec|SpecSection)`, `(Feature)-[:IMPLEMENTED_IN]->(File)` (glob-expanded), `(Feature)-[:USES_TABLE]->(Table)`. Declared in spec frontmatter so links come from the author, not inference. Example (format TBD to match the user's specs):
   ```yaml
   feature: billing
   domain: payments
   implements: ["src/billing/**", "api/routes/invoices.ts"]
   tables: [invoices, invoice_items]
   ```
   Also derived: `(Task)-[:TOUCHES]->(File)` from `complete_task(files_touched)` and commits; `(Deviation)-[:AFFECTS]->(File|Table)`.

**Deferred (step 5, stretch only):** function/class-level symbols and call graphs (e.g. tree-sitter) for the user's main languages. A full code graph is a separate idea on jexp/relate-ideas, and agents already grep well.

**Sync rules for the codebase layer:**
- The daemon's watcher covers source files and schema files too. Hash files, re-parse only changed ones, and **delete nodes/relationships for removed or renamed files**. Stale data is worse than none, because agents trust it.
- Feature globs are re-expanded when files are added or removed.
- Git sync runs on daemon start and on new commits (watch `.git/HEAD` / refs, or poll).
- Each node carries `last_synced` so tools can flag stale context.

**New/updated MCP tools for this layer:**
- `find_code(feature? | domain? | table? | text?)`: files implementing a feature, files touching a table, etc.
- `impact(target)`: given a spec section, table, column or file, return affected features, tasks (open and done), deviations, files and specs. **This is the centrepiece demo query.**
- `explain(file)`: why a file exists: its feature → spec → tasks/commits → deviations that shaped it.
- `get_context(task_id)` is extended to include the task's feature files and tables.

### 5b. Packaging

- **One Python package, used mainly as a tool.** Layout (names TBD): `sdd/parser/` (specs, milestones, deviations, schema files), `sdd/graph/` (all Relate access via `import relate`), `sdd/sync/` (file watcher + git sync), `sdd/mcp/` (MCP server), `sdd/web/` (dashboard), `sdd/cli.py` (`sdd` command).
- Three ways to use it: the **CLI** for humans (`sdd init`, `sdd daemon`, `sdd status`, `sdd impact <target>`, `sdd export`), **MCP** for agents (via the running daemon), and an optional **Python API** (`from sdd import Graph`) for custom scripts or CI checks. The CLI, MCP and web layers stay thin over the same core functions.
- Install paths: `pip install` / `uvx`, and `docker compose up` (see 5d).

### 5c. Views: making the stored data visible to judges

Judges engage far more with something they can see, and terminal logs alone demo badly. Build the dashboard as a **plain static web app** (HTML/JS, no heavy framework) talking to a small JSON API, so the same code serves the local, hosted and static variants.

1. **Local web dashboard (must-have).** Served by the daemon at `http://localhost:<port>`:
   - **Graph view:** interactive diagram of specs, tasks, features, domains, files, tables and deviations (e.g. Cytoscape.js). Click a node to expand its neighbours; filter by label.
   - **Milestone board:** TODO / IN_PROGRESS / DONE columns, updating live (SSE or polling) as subagents claim and complete tasks. Shows which agent holds which task. **Best demo-video moment.**
   - **Impact view:** pick a table, column, spec section or file and highlight everything `impact()` returns.
   - **Explain view:** pick a file and show its chain: feature → spec → tasks/commits → deviations.
   - **Read-only Cypher box** with a few example queries.
2. **Mermaid diagrams in the README (must-have).** `sdd export --mermaid <query|preset>` renders query results as Mermaid. GitHub renders Mermaid natively, so the schema and a sample impact chain are visible on the repo page before anyone runs anything. (Matches "Mermaid as a Query Result" on jexp/relate-ideas.)
3. **Static zero-install demo on GitHub Pages (high value).** Export the sample project's graph; a static page loads it into **Relate's WASM build** (`@relate/relate-wasm`, in-memory) and reuses the dashboard UI minus live updates. Judges click a README link and explore and query with nothing installed. It also showcases a second Relate surface (good for the 30-point criterion). See open question 12.
4. **Neo4j Browser (bonus, near-free).** `relate serve --database .sdd/graph --bolt 7687` works with Neo4j Browser out of the box (per Relate README); the judges know that tool well. Document it in one README section. See open question 11.
5. **Readable committed snapshot (bonus).** Besides the real store, commit a JSON-codec copy (`--snapshot-format json` → readable `graph.json`) and/or a `.rl` made with `relate clone`, so judges inspecting files see understandable data.

### 5d. Docker + live hosted demo (user's home server)

The user runs a home server with Docker and **Cloudflare Tunnels**. Use it for a **live** public demo with the real daemon running.

```
Internet → Cloudflare Tunnel (HTTPS) → home server
                                        └─ docker compose: sdd daemon + dashboard
                                             (sample project; public side read-only)
```

- **Ship `Dockerfile` + `docker-compose.yml` in the repo.** Judges can run the full demo with `docker compose up` (good for the 15-point reproducibility score), and the same files deploy to the home server. Relate's own repo has a Dockerfile (multi-stage, `FROM scratch` runtime) to learn from.
- **Sprint replay mode:** a flag/service (e.g. `sdd demo --replay`) where simulated agents claim, work on, log deviations for and complete tasks on the sample project every few seconds or minutes, then reset the store and loop. Judges opening the link at any time see the board moving and the graph changing.
- **Security (non-negotiable):**
  - Public side exposes **only** the dashboard and read-only queries. **Never** expose the agent MCP endpoint or any write tool publicly. Separate route/port, or separate read-only process.
  - Public queries go through a store opened **read-only** (`--read-only` / `--read-only=live` following the replay writer), so even a buggy route can't write.
  - Set Relate limits (`--logical-graph-size-limit`, query timeouts, row cap via `--max-rows`) so one heavy Cypher query can't hog the server. Consider allowlisting preset queries for the public box or capping complexity.
  - Container CPU/memory limits; isolated Docker network away from the user's other apps; Cloudflare rate limiting / WAF rules.
  - TLS is terminated by Cloudflare (Relate's own server is plaintext only); keep the container off public ports.
- **Uptime:** judging likely runs weeks past Dec 11 and home servers go down (power/ISP/reboots). README links both: **"Live demo (home-hosted) · Static demo (GitHub Pages, always up)."** Add a basic health check / auto-restart (`restart: unless-stopped`).
- **It complements, never replaces, local reproducibility.** The rules require clone-and-run, so `pip install` → `sdd daemon` must work standalone.

### Draft MCP tools
- `next_tasks(milestone?)`: unblocked, unclaimed tasks.
- `claim_task(task_id, agent)`: atomic; fails if already claimed.
- `get_context(task_id)`: minimal packet: governing spec sections + amending deviations + upstream task outcomes + related code artifacts.
- `log_deviation(task_id, reason, amends, impact)`: writes to the graph **and** appends to the deviation Markdown, so humans see it.
- `complete_task(task_id, files_touched, notes)`: marks done, links artifacts, unblocks dependents.
- `what_changed(since)`: spec edits and deviations since a timestamp or session.
- `query(cypher)`: read-only escape hatch.

### Open questions for the spec phase
1. Exact Markdown conventions to parse (frontmatter? heading IDs? how specs, milestones and tasks reference each other today). **Ask the user for a sample of their real spec/milestone/deviation files.**
2. Two-way sync rules: which graph writes flow back to Markdown (task status, deviations), and how to avoid watcher feedback loops.
3. Does `CLAUDE.md` become auto-generated (an export view of graph state)?
4. Spec granularity: whole file vs. per-heading `SpecSection` nodes.
5. Whether to use vector search (semantic lookup of spec sections) in v1 or as a stretch goal.
6. Confirm the Python MCP SDK supports streamable HTTP cleanly, and that `relate-db` exposes explicit transactions in Python (check `docs/api/python/`).
7. Which schema/migration formats the user's projects use (decides the table parser to build first).
8. Frontmatter format for feature/domain/implements/tables declarations, matched to the user's existing spec style.
9. Reuse Relate's `fs-to-graph` / `git-to-graph` extensions vs. our own walkers. Check how extensions run (`relate run <name>` over MCP stdio; the host owns the store) against the single-daemon design.
10. **`relate-db` platform check (do this first):** confirm `pip install relate-db` installs prebuilt wheels on macOS (arm64 + x86_64), Linux (x86_64 + arm64, incl. inside a slim Docker image) and Windows x64, with no Rust toolchain required. Note supported Python versions. If a platform lacks wheels, document it and make Docker the recommended path there.
11. Can the hosted Neo4j Browser (browser.neo4j.io, HTTPS) connect to a local `relate serve --bolt` (plaintext, loopback), or is Neo4j Desktop / a local browser build needed? Test before documenting.
12. Can the browser WASM build (`@relate/relate-wasm`) load an exported graph (Cypher script / JSON) quickly enough for the static demo? What's the best export format?

---

## 6. Demo / judging strategy

- **Lead with numbers.** Run the same milestone two ways, (a) plain Markdown workflow vs. (b) SDD graph, and show tokens read per agent, collisions avoided, and "what changed since last session" answered by one query instead of a re-read.
- **Centrepiece "this needs a graph" moment:** run `impact` on a table or spec section (e.g. "change the `invoices` table") and show everything affected: features, specs, open and done tasks, deviations, files. Then edit a spec and show a subagent's `get_context` change automatically.
- **Answer "why not SQLite?" explicitly**, with multi-hop questions: spec → feature → file → table, and file → task → spec → deviation (`explain`).
- Live moment: the dashboard's milestone board showing tasks flip from TODO → IN_PROGRESS → DONE as parallel subagents work, with the graph view updating. Visuals over terminal logs (see §5c).
- README top: links to the **live hosted demo** and the **static GitHub Pages demo**, a Mermaid schema diagram, and a GIF of the live board.
- Ship a **sample project** with pre-populated specs, milestones and a committed store, so judges can clone and run in minutes.
- README: how and why Relate is used (directory store + daemon, single-process rule), what connects to what (schema diagram), comparison with Spec Kit and Beads.

---

## 7. Suggested timeline (≈3.5 weeks)

- **Week 1 (Nov 17–23):** `relate-db` platform check first. Specs + milestones (in the user's SDD format), Markdown parser, graph schema, daemon skeleton with Relate.
- **Week 2 (Nov 24–30):** MCP tools, claim/complete/deviation flows, Claude Code integration, sample project. Codebase layer steps 1–2 (files/folders, git history). Dashboard skeleton (graph view + milestone board) + JSON API. Dockerfile/compose early, so the home-server deploy is never a last-minute problem.
- **Week 3 (Dec 1–7):** codebase layer steps 3–4 (table parser, feature/domain frontmatter), `impact` / `explain` / `find_code` + their dashboard views, Mermaid export, sprint replay mode, deploy to home server via Cloudflare Tunnel, two-way sync polish, benchmark (Markdown vs. graph). Then the static GitHub Pages (WASM) demo. Stretch: Neo4j Browser docs, vector search, global lessons, step 5 symbols.
- **Final days (Dec 8–11):** README (demo links, Mermaid diagrams, GIF), committed store + readable JSON snapshot, demo video, GitHub topics, Devpost submission. Submit by Dec 11 PST.

---

## 8. First instruction for Claude Code

1. Read this file fully.
2. Ask the user for sample spec / milestone / deviation / CLAUDE.md files from one of their real projects, plus a sample schema/migration file, and match their format.
3. Run the `relate-db` platform check (open question 10) and review the Relate Python API (`docs/api/python/`) before finalizing the design. Then resolve the remaining open questions in §5 with the user.
4. Write the project's own specs and milestones **in the user's SDD format** (this project is built with the same workflow it improves).
