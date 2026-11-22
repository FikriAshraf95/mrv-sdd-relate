// Details `explain` adds to the file traversals of impact.cypher (SPEC-06 §3). Parameters only.

// name: explain.file
MATCH (f:File {id: $id})
RETURN f.id AS id, f.path AS path, f.language AS language, f.is_test AS is_test

// name: explain.features
MATCH (f:Feature) WHERE f.id IN $ids
OPTIONAL MATCH (f)-[:BELONGS_TO]->(d:Domain)
RETURN f.id AS id, f.name AS name, f.slug AS slug, d.name AS domain

// name: explain.feature_specs
MATCH (f:Feature)-[:SPECIFIED_BY]->(p:Spec) WHERE f.id IN $ids
RETURN f.id AS feature, p.id AS spec

// name: explain.tasks
MATCH (t:Task) WHERE t.id IN $ids
RETURN t.id AS id, t.title AS title, t.status AS status, t.milestone_id AS milestone, t.notes AS notes

// name: explain.commits
MATCH (c:Commit) WHERE c.id IN $ids
OPTIONAL MATCH (c)-[:COMPLETES]->(t:Task)
RETURN c.id AS id, c.sha AS sha, c.short AS short, c.message AS message, c.at AS at, t.id AS task

// name: explain.checks
MATCH (a:AcceptanceCheck) WHERE a.id IN $ids
RETURN a.id AS id, a.spec_id AS spec_id, a.text AS text
