"""Labels, constraints and indexes (SPEC-02 §1, §6), and store counts.

Relate supports uniqueness constraints, range indexes and full-text indexes, all created inside a
transaction and idempotent with ``IF NOT EXISTS`` (open item O6), so every label gets a unique
``id`` and both stretch full-text indexes exist. Full-text search runs through
``CALL db.index.fulltext.queryNodes(name, text)``; the query guard rejects ``CALL``, so it is
for ``service/`` code only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sdd.graph.store import Store, Tx

SCHEMA_VERSION = 1

# SPEC-02 §1: every label. A new label is added here and there in the same change.
LABELS: tuple[str, ...] = (
    "Spec",
    "Section",
    "AcceptanceCheck",
    "Milestone",
    "Task",
    "Deviation",
    "Doc",
    "Folder",
    "File",
    "Commit",
    "Table",
    "Column",
    "Feature",
    "Domain",
    "Agent",
    "Event",
    "Meta",
)

# SPEC-02 §6
PROPERTY_INDEXES: tuple[tuple[str, str], ...] = (
    ("Task", "status"),
    ("Task", "milestone_id"),
    ("File", "path"),
    ("Section", "spec_id"),
    ("Event", "at"),
)
FULLTEXT_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ft_section_text": ("Section", ("title", "text")),
    "ft_file_path": ("File", ("path",)),
}


def constraint_name(label: str) -> str:
    return f"uniq_{label.lower()}_id"


def index_name(label: str, prop: str) -> str:
    return f"idx_{label.lower()}_{prop}"


def statements() -> list[str]:
    """Every schema statement, idempotent."""
    out = [
        f"CREATE CONSTRAINT {constraint_name(label)} IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        for label in LABELS
    ]
    out += [
        f"CREATE INDEX {index_name(label, prop)} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
        for label, prop in PROPERTY_INDEXES
    ]
    for name, (label, props) in FULLTEXT_INDEXES.items():
        fields = ", ".join(f"n.{p}" for p in props)
        out.append(f"CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR (n:{label}) ON EACH [{fields}]")
    return out


def ensure(store: Store) -> None:
    """Create every constraint and index that is missing, in one write job."""

    def job(tx: Tx) -> None:
        for statement in statements():
            tx.run(statement)

    store.write(job)


def defined(store: Store) -> tuple[set[str], set[str]]:
    """Names of the constraints and of the non-lookup indexes in the store."""
    constraints = {row["name"] for row in store.read("SHOW CONSTRAINTS")}
    indexes = {row["name"] for row in store.read("SHOW INDEXES") if row["type"] != "LOOKUP"}
    return constraints, indexes


@dataclass(frozen=True)
class Counts:
    nodes: dict[str, int]
    relationships: dict[str, int]

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes.values())

    @property
    def total_relationships(self) -> int:
        return sum(self.relationships.values())


def counts(store: Store) -> Counts:
    """Node count per label and relationship count per type, sorted by name.

    A node with two labels counts under both.
    """
    nodes = store.read(
        "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n ORDER BY label"
    )
    rels = store.read("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type")
    return Counts(
        nodes={row["label"]: row["n"] for row in nodes},
        relationships={row["type"]: row["n"] for row in rels},
    )


def store_schema_version(store: Store) -> int | None:
    """``Meta.schema_version`` (SPEC-02 §2), or ``None`` before the first sync writes it."""
    rows = store.read("MATCH (m:Meta {id: 'meta'}) RETURN m.schema_version AS v")
    return rows[0]["v"] if rows else None
