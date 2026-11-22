// Routes behind `find_code` (SPEC-06 §4). Each query returns files with the chain that reaches
// them: id, path, language, via. Parameters only. `~PATH` in a via is not a relationship: the
// file's path names the table in a migrations or models folder.

// name: find.feature
MATCH (f:Feature {id: $id})-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language, [f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: find.domain
MATCH (d:Domain {id: $id})<-[:BELONGS_TO]-(f:Feature)-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language,
       [d.id, '<-BELONGS_TO', f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: find.table.features
MATCH (t:Table {id: $id})<-[:USES_TABLE]-(f:Feature)-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language,
       [t.id, '<-USES_TABLE', f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: find.table.mentions
MATCH (t:Table {id: $id})<-[:MENTIONS]-(n)-[:MENTIONS]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language,
       [t.id, '<-MENTIONS', n.id, '->MENTIONS', x.id] AS via

// name: find.table.affects
MATCH (t:Table {id: $id})<-[:AFFECTS]-(d:Deviation)-[:AFFECTS]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language,
       [t.id, '<-AFFECTS', d.id, '->AFFECTS', x.id] AS via

// name: find.table.paths
MATCH (t:Table {id: $id})
MATCH (x:File)
WHERE (('/' + toLower(x.path)) CONTAINS '/migrations/' OR ('/' + toLower(x.path)) CONTAINS '/models/')
  AND toLower(x.path) CONTAINS toLower(t.name)
RETURN x.id AS id, x.path AS path, x.language AS language, [t.id, '~PATH', x.id] AS via

// name: find.spec.features
MATCH (p:Spec {id: $id})<-[:SPECIFIED_BY]-(f:Feature)-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language,
       [p.id, '<-SPECIFIED_BY', f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: find.spec.mentions
MATCH (p:Spec {id: $id})
MATCH (s:Section {spec_id: p.id})-[:MENTIONS]->(x:File)
RETURN x.id AS id, x.path AS path, x.language AS language,
       [p.id, '->HAS_SECTION', s.id, '->MENTIONS', x.id] AS via

// name: find.text
MATCH (x:File) WHERE toLower(x.path) CONTAINS toLower($text)
RETURN x.id AS id, x.path AS path, x.language AS language, [x.id] AS via
