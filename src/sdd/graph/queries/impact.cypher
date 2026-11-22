// Fixed traversals behind `impact` (SPEC-06 §2). Every query returns one row per item:
// id, label, title, status and `via`, the chain from the target to the item (->T / <-T give
// the stored direction). `service/impact.py` picks the queries by target label and assembles
// groups, hops and caps. Parameters only: $id (one node) or $ids (section IDs).

// name: impact.table.columns
MATCH (t:Table {id: $id})-[:HAS_COLUMN]->(x:Column)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '->HAS_COLUMN', x.id] AS via

// name: impact.table.dependents
MATCH (t:Table {id: $id})<-[:REFERENCES]-(c:Column)<-[:HAS_COLUMN]-(x:Table)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-REFERENCES', c.id, '<-HAS_COLUMN', x.id] AS via

// name: impact.table.defining_section
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(x:Section)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', x.id] AS via

// name: impact.table.defining_spec
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(s:Section)
MATCH (x:Spec {id: s.spec_id})
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', s.id, '<-HAS_SECTION', x.id] AS via

// name: impact.table.mentions
MATCH (t:Table {id: $id})<-[:MENTIONS]-(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-MENTIONS', x.id] AS via

// name: impact.table.linking_sections
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(s:Section)<-[:LINKS_TO]-(x:Section)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', s.id, '<-LINKS_TO', x.id] AS via

// name: impact.table.features
MATCH (t:Table {id: $id})<-[:USES_TABLE]-(x:Feature)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-USES_TABLE', x.id] AS via

// name: impact.table.feature_files
MATCH (t:Table {id: $id})<-[:USES_TABLE]-(f:Feature)-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-USES_TABLE', f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: impact.table.feature_specs
MATCH (t:Table {id: $id})<-[:USES_TABLE]-(f:Feature)-[:SPECIFIED_BY]->(x:Spec)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-USES_TABLE', f.id, '->SPECIFIED_BY', x.id] AS via

// name: impact.table.tasks_by_defining_section
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(s:Section)<-[:GOVERNED_BY]-(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', s.id, '<-GOVERNED_BY', x.id] AS via

// name: impact.table.tasks_by_mentioning_section
MATCH (t:Table {id: $id})<-[:MENTIONS]-(s:Section)<-[:GOVERNED_BY]-(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-MENTIONS', s.id, '<-GOVERNED_BY', x.id] AS via

// name: impact.table.deviations_affects
MATCH (t:Table {id: $id})<-[:AFFECTS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-AFFECTS', x.id] AS via

// name: impact.table.deviations_amending_defining
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(s:Section)<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', s.id, '<-AMENDS', x.id] AS via

// name: impact.table.deviations_amending_mentioning
MATCH (t:Table {id: $id})<-[:MENTIONS]-(s:Section)<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-MENTIONS', s.id, '<-AMENDS', x.id] AS via

// name: impact.table.checks
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(s:Section)
MATCH (p:Spec {id: s.spec_id})-[:HAS_CHECK]->(x:AcceptanceCheck)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', s.id, '<-HAS_SECTION', p.id, '->HAS_CHECK', x.id] AS via

// name: impact.table.test_files
MATCH (t:Table {id: $id})<-[:DEFINES_TABLE]-(s:Section)
MATCH (p:Spec {id: s.spec_id})-[:HAS_CHECK]->(a:AcceptanceCheck)<-[:TESTS]-(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-DEFINES_TABLE', s.id, '<-HAS_SECTION', p.id, '->HAS_CHECK', a.id, '<-TESTS', x.id] AS via

// name: impact.column.references
MATCH (c:Column {id: $id})-[:REFERENCES]->(x:Table)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [c.id, '->REFERENCES', x.id] AS via

// name: impact.column.same_target
MATCH (c:Column {id: $id})-[:REFERENCES]->(t:Table)<-[:REFERENCES]-(x:Column)
WHERE x.id <> c.id
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [c.id, '->REFERENCES', t.id, '<-REFERENCES', x.id] AS via

// name: impact.column.table
MATCH (c:Column {id: $id})<-[:HAS_COLUMN]-(x:Table)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [c.id, '<-HAS_COLUMN', x.id] AS via

// name: impact.spec.sections
MATCH (p:Spec {id: $id})
MATCH (x:Section {spec_id: p.id})
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '->HAS_SECTION', x.id] AS via

// name: impact.spec.milestones
MATCH (p:Spec {id: $id})<-[:READS]-(x:Milestone)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '<-READS', x.id] AS via

// name: impact.spec.tasks
MATCH (p:Spec {id: $id})<-[:GOVERNED_BY]-(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '<-GOVERNED_BY', x.id] AS via

// name: impact.spec.deviations
MATCH (p:Spec {id: $id})<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '<-AMENDS', x.id] AS via

// name: impact.spec.linking
MATCH (p:Spec {id: $id})<-[:LINKS_TO]-(x:Section)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '<-LINKS_TO', x.id] AS via

// name: impact.spec.checks
MATCH (p:Spec {id: $id})-[:HAS_CHECK]->(x:AcceptanceCheck)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '->HAS_CHECK', x.id] AS via

// name: impact.spec.features
MATCH (p:Spec {id: $id})<-[:SPECIFIED_BY]-(x:Feature)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '<-SPECIFIED_BY', x.id] AS via

// name: impact.spec.feature_files
MATCH (p:Spec {id: $id})<-[:SPECIFIED_BY]-(f:Feature)-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '<-SPECIFIED_BY', f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: impact.spec.test_files
MATCH (p:Spec {id: $id})-[:HAS_CHECK]->(a:AcceptanceCheck)<-[:TESTS]-(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [p.id, '->HAS_CHECK', a.id, '<-TESTS', x.id] AS via

// name: impact.section.children
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)-[:HAS_SECTION]->(x:Section)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '->HAS_SECTION', x.id] AS via

// name: impact.section.linking
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)<-[:LINKS_TO]-(x:Section)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-LINKS_TO', x.id] AS via

// name: impact.section.milestones
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)<-[:READS]-(x:Milestone)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-READS', x.id] AS via

// name: impact.section.tasks
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)<-[:GOVERNED_BY]-(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-GOVERNED_BY', x.id] AS via

// name: impact.section.deviations
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-AMENDS', x.id] AS via

// name: impact.section.defined_tables
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)-[:DEFINES_TABLE]->(x:Table)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '->DEFINES_TABLE', x.id] AS via

// name: impact.section.mentioned_tables
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)-[:MENTIONS]->(x:Table)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '->MENTIONS', x.id] AS via

// name: impact.section.mentioned_files
MATCH (s:Section) WHERE s.id IN $ids
MATCH (s)-[:MENTIONS]->(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '->MENTIONS', x.id] AS via

// name: impact.section.features
MATCH (s:Section) WHERE s.id IN $ids
MATCH (p:Spec {id: s.spec_id})<-[:SPECIFIED_BY]-(x:Feature)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-HAS_SECTION', p.id, '<-SPECIFIED_BY', x.id] AS via

// name: impact.section.feature_files
MATCH (s:Section) WHERE s.id IN $ids
MATCH (p:Spec {id: s.spec_id})<-[:SPECIFIED_BY]-(f:Feature)-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-HAS_SECTION', p.id, '<-SPECIFIED_BY', f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: impact.section.checks
MATCH (s:Section) WHERE s.id IN $ids
MATCH (p:Spec {id: s.spec_id})-[:HAS_CHECK]->(x:AcceptanceCheck)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-HAS_SECTION', p.id, '->HAS_CHECK', x.id] AS via

// name: impact.section.test_files
MATCH (s:Section) WHERE s.id IN $ids
MATCH (p:Spec {id: s.spec_id})-[:HAS_CHECK]->(a:AcceptanceCheck)<-[:TESTS]-(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [s.id, '<-HAS_SECTION', p.id, '->HAS_CHECK', a.id, '<-TESTS', x.id] AS via

// name: impact.file.features
MATCH (f:File {id: $id})<-[:IMPLEMENTED_IN]-(x:Feature)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-IMPLEMENTED_IN', x.id] AS via

// name: impact.file.feature_specs
MATCH (f:File {id: $id})<-[:IMPLEMENTED_IN]-(g:Feature)-[:SPECIFIED_BY]->(x:Spec)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-IMPLEMENTED_IN', g.id, '->SPECIFIED_BY', x.id] AS via

// name: impact.file.mentions
MATCH (f:File {id: $id})<-[:MENTIONS]-(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-MENTIONS', x.id] AS via

// name: impact.file.touching_tasks
MATCH (f:File {id: $id})<-[:TOUCHES]-(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-TOUCHES', x.id] AS via

// name: impact.file.commits
MATCH (f:File {id: $id})<-[:CHANGED]-(x:Commit)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-CHANGED', x.id] AS via
ORDER BY x.at DESC
LIMIT 10

// name: impact.file.commit_tasks
MATCH (f:File {id: $id})<-[:CHANGED]-(c:Commit)
WITH f, c ORDER BY c.at DESC LIMIT 10
MATCH (c)-[:COMPLETES]->(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-CHANGED', c.id, '->COMPLETES', x.id] AS via

// name: impact.file.deviations_affects
MATCH (f:File {id: $id})<-[:AFFECTS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-AFFECTS', x.id] AS via

// name: impact.file.deviations_amending_sections
MATCH (f:File {id: $id})<-[:IMPLEMENTED_IN]-(g:Feature)-[:SPECIFIED_BY]->(p:Spec)
MATCH (s:Section {spec_id: p.id})<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-IMPLEMENTED_IN', g.id, '->SPECIFIED_BY', p.id, '->HAS_SECTION', s.id, '<-AMENDS', x.id] AS via

// name: impact.file.deviations_amending_specs
MATCH (f:File {id: $id})<-[:IMPLEMENTED_IN]-(g:Feature)-[:SPECIFIED_BY]->(p:Spec)<-[:AMENDS]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '<-IMPLEMENTED_IN', g.id, '->SPECIFIED_BY', p.id, '<-AMENDS', x.id] AS via

// name: impact.file.checks
MATCH (f:File {id: $id})-[:TESTS]->(x:AcceptanceCheck)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '->TESTS', x.id] AS via

// name: impact.feature.files
MATCH (f:Feature {id: $id})-[:IMPLEMENTED_IN]->(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '->IMPLEMENTED_IN', x.id] AS via

// name: impact.feature.tables
MATCH (f:Feature {id: $id})-[:USES_TABLE]->(x:Table)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '->USES_TABLE', x.id] AS via

// name: impact.feature.specs
MATCH (f:Feature {id: $id})-[:SPECIFIED_BY]->(x:Spec)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '->SPECIFIED_BY', x.id] AS via

// name: impact.feature.domain
MATCH (f:Feature {id: $id})-[:BELONGS_TO]->(x:Domain)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [f.id, '->BELONGS_TO', x.id] AS via

// name: impact.domain.features
MATCH (d:Domain {id: $id})<-[:BELONGS_TO]-(x:Feature)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [d.id, '<-BELONGS_TO', x.id] AS via

// name: impact.task.milestone
MATCH (t:Task {id: $id})<-[:INCLUDES]-(x:Milestone)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-INCLUDES', x.id] AS via

// name: impact.task.governing
MATCH (t:Task {id: $id})-[:GOVERNED_BY]->(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '->GOVERNED_BY', x.id] AS via

// name: impact.task.blocked_by
MATCH (t:Task {id: $id})-[:BLOCKED_BY]->(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '->BLOCKED_BY', x.id] AS via

// name: impact.task.blocking
MATCH (t:Task {id: $id})<-[:BLOCKED_BY]-(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-BLOCKED_BY', x.id] AS via

// name: impact.task.touches
MATCH (t:Task {id: $id})-[:TOUCHES]->(x:File)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '->TOUCHES', x.id] AS via

// name: impact.task.commits
MATCH (t:Task {id: $id})<-[:COMPLETES]-(x:Commit)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-COMPLETES', x.id] AS via

// name: impact.task.deviations
MATCH (t:Task {id: $id})<-[:RAISED_IN]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [t.id, '<-RAISED_IN', x.id] AS via

// name: impact.milestone.tasks
MATCH (m:Milestone {id: $id})-[:INCLUDES]->(x:Task)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [m.id, '->INCLUDES', x.id] AS via

// name: impact.milestone.reads
MATCH (m:Milestone {id: $id})-[:READS]->(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [m.id, '->READS', x.id] AS via

// name: impact.milestone.depends_on
MATCH (m:Milestone {id: $id})-[:DEPENDS_ON]->(x:Milestone)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [m.id, '->DEPENDS_ON', x.id] AS via

// name: impact.milestone.depended_on
MATCH (m:Milestone {id: $id})<-[:DEPENDS_ON]-(x:Milestone)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [m.id, '<-DEPENDS_ON', x.id] AS via

// name: impact.milestone.deviations
MATCH (m:Milestone {id: $id})<-[:RAISED_IN]-(x:Deviation)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [m.id, '<-RAISED_IN', x.id] AS via

// name: impact.milestone.commits
MATCH (m:Milestone {id: $id})<-[:PART_OF]-(x:Commit)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [m.id, '<-PART_OF', x.id] AS via

// name: impact.deviation.amends
MATCH (d:Deviation {id: $id})-[:AMENDS]->(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [d.id, '->AMENDS', x.id] AS via

// name: impact.deviation.affects
MATCH (d:Deviation {id: $id})-[:AFFECTS]->(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [d.id, '->AFFECTS', x.id] AS via

// name: impact.deviation.raised_in
MATCH (d:Deviation {id: $id})-[:RAISED_IN]->(x)
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.title, x.name, x.path, x.message, x.id) AS title, x.status AS status,
       [d.id, '->RAISED_IN', x.id] AS via
