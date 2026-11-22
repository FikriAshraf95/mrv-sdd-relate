// Graphs behind the presets (SPEC-06 §5). Parameters only.

// name: presets.nodes
MATCH (n) WHERE n.id IN $ids
RETURN labels(n)[0] AS label, properties(n) AS p

// name: presets.schema_nodes
MATCH (n)
RETURN labels(n)[0] AS label, count(*) AS count

// name: presets.schema_edges
MATCH (a)-[r]->(b)
RETURN labels(a)[0] AS from_label, type(r) AS type, labels(b)[0] AS to_label, count(*) AS count

// name: presets.lineage.deviations
MATCH (s:Section {id: $id})<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, [s.id, '<-AMENDS', x.id] AS via

// name: presets.lineage.raised_in
MATCH (s:Section {id: $id})<-[:AMENDS]-(d:Deviation)-[:RAISED_IN]->(x)
RETURN x.id AS id, [s.id, '<-AMENDS', d.id, '->RAISED_IN', x.id] AS via

// name: presets.lineage.touched
MATCH (s:Section {id: $id})<-[:AMENDS]-(d:Deviation)-[:RAISED_IN]->(t:Task)-[:TOUCHES]->(x:File)
RETURN x.id AS id, [s.id, '<-AMENDS', d.id, '->RAISED_IN', t.id, '->TOUCHES', x.id] AS via
