"""SPEC-10 §4 invariant 7: the query guard rejects every write clause in a fixed corpus."""

from __future__ import annotations

import pytest

from sdd.errors import SddError
from sdd.service import query_guard

CORPUS = (
    "CREATE (n:Task {id: 'M99.1'})",
    "create (n)",
    "MATCH (a), (b) CREATE (a)-[:LINKS_TO]->(b)",
    "MERGE (n:Agent {id: 'agent:x'})",
    "MATCH (n) SET n.title = 'x'",
    "MATCH (n) SET n:Hacked",
    "MATCH (n) SET n += {x: 1}",
    "MATCH (n) DELETE n",
    "MATCH (n) DETACH DELETE n",
    "MATCH (n)\nDETACH\nDELETE n",
    "MATCH (n) /* note */ DeLeTe n",
    "MATCH (n) REMOVE n.title",
    "MATCH (n) REMOVE n:Task",
    "DROP INDEX idx_task_status",
    "DROP CONSTRAINT uniq_task_id",
    "CREATE INDEX x IF NOT EXISTS FOR (n:X) ON (n.y)",
    "LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row",
    "FOREACH (x IN [1, 2] | CREATE (:X))",
    "UNWIND [1, 2] AS x CREATE (:X {v: x})",
    "CALL db.labels()",
    "CALL { CREATE (:X) }",
    "MATCH (n) CALL { WITH n DELETE n } IN TRANSACTIONS",
    "MATCH (n) WITH n IN TRANSACTIONS RETURN n",
    "USE system SHOW DATABASES",
    "RETURN 1; MATCH (n) DELETE n",
    "MATCH (n) RETURN n ; CREATE (:X)",
    "OPTIONAL MATCH (n) WITH n MERGE (m:X) RETURN m",
)


@pytest.mark.parametrize("cypher", CORPUS)
def test_inv07_guard_rejects_every_write(cypher: str) -> None:
    with pytest.raises(SddError) as err:
        query_guard.check(cypher)
    assert err.value.code == "query_rejected"
