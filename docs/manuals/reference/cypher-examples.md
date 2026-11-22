# Example Cypher queries

> For the dashboard's **Query** tab, `sdd query '<cypher>'` and the MCP `query` tool. Every query here was run against the Courtside sample.

## Rules of the query guard

- **Read-only.** `CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH`, `REMOVE`, `DROP`, `LOAD`, `FOREACH`, `CALL`, `USE`, `IN TRANSACTIONS` and a second statement are rejected (`query_rejected`). The query also runs in a transaction that is always rolled back.
- **Bounded paths.** Variable-length patterns need an upper bound of at most 4: `-[*..4]-` is fine, `-[*]-` and `-[*2..]-` are rejected.
- **100 rows** (`truncated: true` beyond), **5 seconds**, one guarded query at a time per process, in a worker with a memory cap.
- **Nodes come back as property maps.** `RETURN t` gives `{id, title, status, …}`. In the dashboard, a result with nodes offers *Show as graph*.
- Map properties are stored as JSON strings: `Spec.header` is `header_json`, `Event.data` is `data_json`.
- After aggregation, `ORDER BY` can only use returned columns. Return `m.order AS ord` and order by `ord`.

The [Graph schema](graph-schema.md) lists every label, property and relationship.

## Progress

**Milestones with done/total, in order**

```cypher
MATCH (m:Milestone)-[:INCLUDES]->(t:Task)
RETURN m.order AS ord, m.id AS milestone, m.status AS status, count(t) AS tasks,
       sum(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done
ORDER BY ord
```

**Open tasks** (the dashboard's first example)

```cypher
MATCH (t:Task) WHERE t.status <> 'done'
RETURN t.id AS id, t.title AS title, t.status AS status ORDER BY id LIMIT 50
```

**Who holds what right now**

```cypher
MATCH (t:Task) WHERE t.claimed_by IS NOT NULL
RETURN t.id, t.claimed_by, t.claimed_at ORDER BY t.claimed_at
```

**Tasks still waiting on another task**

```cypher
MATCH (t:Task {status: 'todo'})-[:BLOCKED_BY]->(b:Task) WHERE b.status <> 'done'
RETURN t.id AS task, collect(b.id) AS waiting_on ORDER BY task
```

**Recent activity** (graph-only events)

```cypher
MATCH (e:Event) RETURN e.at, e.kind, e.actor, e.target_id ORDER BY e.at DESC LIMIT 20
```

## Spec hygiene

**Task lines that link no section** (they get no packet saving)

```cypher
MATCH (t:Task) WHERE NOT (t)-[:GOVERNED_BY]->() RETURN t.id, t.title ORDER BY t.id
```

**Top-level sections no task is governed by**

```cypher
MATCH (s:Section) OPTIONAL MATCH (s)<-[g:GOVERNED_BY]-(:Task)
WITH s, count(g) AS tasks WHERE tasks = 0 AND s.level = 2
RETURN s.id, s.title ORDER BY s.id
```

**Acceptance checks without a test**

```cypher
MATCH (c:AcceptanceCheck) WHERE NOT (c)<-[:TESTS]-() RETURN c.id, c.text ORDER BY c.id
```

**Unresolved links**

```cypher
MATCH (n) WHERE n.unresolved IS NOT NULL RETURN n.id, n.unresolved
```

**Sections changed since the store's first sync**

```cypher
MATCH (s:Section) WHERE s.changed_at IS NOT NULL
RETURN s.id, s.title, s.changed_at ORDER BY s.changed_at DESC LIMIT 20
```

**What each milestone reads**

```cypher
MATCH (m:Milestone)-[r:READS]->(s) RETURN m.id, s.id, r.whole ORDER BY m.id
```

## Deviations and lineage

**Open deviations and the sections they amend**

```cypher
MATCH (d:Deviation {status: 'open'})-[:AMENDS]->(s:Section)
RETURN d.id, d.title, collect(DISTINCT s.id) AS amends ORDER BY d.id
```

**Open tasks whose governing section a deviation amends** (the agent must know before building)

```cypher
MATCH (d:Deviation)-[:AMENDS]->(s:Section)<-[:GOVERNED_BY]-(t:Task) WHERE t.status <> 'done'
RETURN DISTINCT d.id AS deviation, s.id AS section, t.id AS open_task ORDER BY deviation
```

**Deviations on one task's sections**

```cypher
MATCH (t:Task {id: 'M05a.3'})-[:GOVERNED_BY]->(s:Section)<-[:AMENDS]-(d:Deviation)
RETURN DISTINCT s.id, d.id, d.status
```

**Files within 3 hops of a deviation**

```cypher
MATCH (d:Deviation {id: 'D006'})-[*..3]-(f:File) RETURN DISTINCT f.path LIMIT 20
```

## Code and history

**Commits per task**

```cypher
MATCH (c:Commit)-[:COMPLETES]->(t:Task) RETURN t.id, collect(c.short) AS commits ORDER BY t.id
```

**Done tasks no commit names** (commit messages should carry `[M05a.2]`)

```cypher
MATCH (t:Task {status: 'done'}) WHERE NOT (t)<-[:COMPLETES]-(:Commit) RETURN t.id, t.title ORDER BY t.id
```

**Files per feature**

```cypher
MATCH (f:Feature)-[:IMPLEMENTED_IN]->(file:File)
RETURN f.name AS feature, count(file) AS files ORDER BY files DESC
```

**Orphan code** (no feature, mention or task explains it; `explain` gives the same per file)

```cypher
MATCH (f:File) WHERE f.is_test = false AND f.language = 'python'
  AND NOT (f)<-[:IMPLEMENTED_IN]-() AND NOT (f)<-[:MENTIONS]-() AND NOT (f)<-[:TOUCHES]-()
RETURN f.path ORDER BY f.path
```

**Foreign keys between schema tables**

```cypher
MATCH (t:Table)-[:HAS_COLUMN]->(c:Column)-[:REFERENCES]->(r:Table)
RETURN t.name AS from_table, c.name AS column, r.name AS to_table ORDER BY from_table
```

## The graph itself

**Label counts** (dashboard example)

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC
```

**Relationship counts**

```cypher
MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY n DESC
```

**A subgraph to draw** (use *Show as graph*)

```cypher
MATCH (m:Milestone)-[r:INCLUDES]->(t:Task) RETURN m, r, t LIMIT 40
```

## With parameters

```bash
sdd query 'MATCH (t:Task {milestone_id: $m}) RETURN t.id, t.status ORDER BY t.order' --params '{"m": "M05a"}'
```

```json
query({"cypher": "MATCH (t:Task {milestone_id: $m}) RETURN t.id, t.status ORDER BY t.order", "params": {"m": "M05a"}})
```

## Presets instead of Cypher

The dashboard's **Presets** menu (and `GET /api/presets/{name}`, `sdd export --mermaid <name>`) runs fixed queries that return a graph: `schema`, `milestone:<id>`, `impact:<target>`, `explain:<path>`, `lineage:<section>`, `feature:<slug>`. A public server started with `SDD_PUBLIC_QUERY=presets` runs only these.
