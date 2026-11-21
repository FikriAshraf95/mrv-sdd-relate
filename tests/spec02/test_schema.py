"""SPEC-02 §6 indexes and constraints; store counts."""

from __future__ import annotations

import pytest

from sdd.graph import schema
from sdd.graph.store import Store


def test_ensure_creates_every_constraint_and_index(store: Store) -> None:
    constraints, indexes = schema.defined(store)
    assert constraints == {schema.constraint_name(label) for label in schema.LABELS}
    expected = {schema.index_name(label, prop) for label, prop in schema.PROPERTY_INDEXES}
    expected |= set(schema.FULLTEXT_INDEXES)
    expected |= constraints  # each uniqueness constraint owns an index of the same name
    assert indexes == expected


def test_ensure_is_idempotent(store: Store) -> None:
    before = schema.defined(store)
    schema.ensure(store)
    assert schema.defined(store) == before


@pytest.mark.parametrize("label", schema.LABELS)
def test_unique_id_on_every_label(store: Store, label: str) -> None:
    store.write(lambda tx: tx.run(f"CREATE (:{label} {{id: 'x'}})"))
    with pytest.raises(Exception, match="uniqueness"):
        store.write(lambda tx: tx.run(f"CREATE (:{label} {{id: 'x'}})"))
    store.write(lambda tx: tx.run(f"MERGE (:{label} {{id: 'x'}})"))
    assert store.read(f"MATCH (n:{label}) RETURN count(n) AS c") == [{"c": 1}]


def test_fulltext_section_index_answers(store: Store) -> None:
    store.write(
        lambda tx: tx.run(
            "CREATE (:Section {id: 'SPEC-01#2', title: 'Chunking', text: 'split into chunks'}),"
            " (:Section {id: 'SPEC-01#3', title: 'Auth', text: 'tokens'})"
        )
    )
    rows = store.read(
        "CALL db.index.fulltext.queryNodes('ft_section_text', 'chunks') YIELD node "
        "RETURN node.id AS id"
    )
    assert rows == [{"id": "SPEC-01#2"}]


def test_counts_per_label_and_type(store: Store) -> None:
    assert schema.counts(store) == schema.Counts(nodes={}, relationships={})
    store.write(
        lambda tx: tx.run(
            "CREATE (m:Milestone {id: 'M01'})-[:INCLUDES]->(:Task {id: 'M01.1'}),"
            " (m)-[:INCLUDES]->(:Task {id: 'M01.2'}), (m)-[:GOVERNED_BY]->(:Spec {id: 'SPEC-01'})"
        )
    )
    counts = schema.counts(store)
    assert counts.nodes == {"Milestone": 1, "Spec": 1, "Task": 2}
    assert counts.relationships == {"GOVERNED_BY": 1, "INCLUDES": 2}
    assert (counts.total_nodes, counts.total_relationships) == (4, 3)


def test_store_schema_version_comes_from_meta(store: Store) -> None:
    assert schema.store_schema_version(store) is None
    store.write(lambda tx: tx.run("CREATE (:Meta {id: 'meta', schema_version: 1})"))
    assert schema.store_schema_version(store) == 1
