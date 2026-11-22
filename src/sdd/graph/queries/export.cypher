// The whole graph, for `sdd export --json | --cypher` (SPEC-08 §3). Parameters only.

// name: export.nodes
MATCH (n)
RETURN labels(n)[0] AS label, properties(n) AS p
ORDER BY n.id

// name: export.edges
MATCH (a)-[r]->(b)
RETURN labels(a)[0] AS source_label, a.id AS source, type(r) AS type,
       labels(b)[0] AS target_label, b.id AS target, properties(r) AS p
ORDER BY a.id, type(r), b.id

// name: export.mermaid_nodes
MATCH (n) WHERE n.id IN $ids
RETURN labels(n)[0] AS label, properties(n) AS p
