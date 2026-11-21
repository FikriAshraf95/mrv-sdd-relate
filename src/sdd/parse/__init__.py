"""Pure Markdown parsers: text in, parsed objects out (SPEC-03).

Never raises on bad Markdown; problems are :class:`ParseWarning` entries. No file I/O, no graph:
``sync/`` reads the files and hands the results to ``graph/`` as plain data.
"""

from sdd.parse.deviations import cross_check_index, parse_deviation, parse_deviation_index
from sdd.parse.docs import parse_doc, parse_plan
from sdd.parse.links import Catalog, Found, Resolution, expand_range, resolve
from sdd.parse.milestones import parse_milestone
from sdd.parse.model import (
    WARNING_CODES,
    FeatureLine,
    IndexRow,
    Node,
    ParseResult,
    ParseWarning,
    Ref,
    Rel,
    Severity,
)
from sdd.parse.specs import parse_spec

__all__ = [
    "WARNING_CODES",
    "Catalog",
    "FeatureLine",
    "Found",
    "IndexRow",
    "Node",
    "ParseResult",
    "ParseWarning",
    "Ref",
    "Rel",
    "Resolution",
    "Severity",
    "cross_check_index",
    "expand_range",
    "parse_deviation",
    "parse_deviation_index",
    "parse_doc",
    "parse_milestone",
    "parse_plan",
    "parse_spec",
    "resolve",
]
