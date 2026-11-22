// Lookups behind target resolution (SPEC-06 §2). Parameters only.

// name: resolve.node
MATCH (n {id: $id})
RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.title, n.name, n.path, n.message, n.id) AS title

// name: resolve.table_by_name
MATCH (t:Table) WHERE t.name = $name
RETURN t.id AS id

// name: resolve.column_by_table_and_name
MATCH (c:Column) WHERE c.table = $table AND c.name = $name
RETURN c.id AS id

// name: resolve.columns_by_name
MATCH (c:Column) WHERE c.name = $name
RETURN c.id AS id

// name: resolve.file_by_path
MATCH (f:File) WHERE f.path = $path
RETURN f.id AS id

// name: resolve.files_by_suffix
MATCH (f:File) WHERE f.path ENDS WITH $suffix
RETURN f.id AS id

// name: resolve.features_by_name
MATCH (f:Feature) WHERE f.slug = $slug OR toLower(f.name) = toLower($name)
RETURN f.id AS id

// name: resolve.domains_by_name
MATCH (d:Domain) WHERE d.slug = $slug OR toLower(d.name) = toLower($name)
RETURN d.id AS id

// name: resolve.section_titles
MATCH (s:Section)
OPTIONAL MATCH (s)-[:DEFINES_TABLE]->(t:Table)
WITH s, t WHERE t IS NULL
RETURN s.id AS id, s.title AS title

// name: resolve.spec_section_titles
MATCH (s:Section {spec_id: $spec})
RETURN s.id AS id, s.title AS title
