"""SPEC-03 §1.5 and §2: links, the reference grammar, ranges, notes, resolution."""

from __future__ import annotations

import pytest

from sdd.ids import normalise
from sdd.parse import Catalog, Ref, expand_range, resolve
from sdd.parse.links import backticked, deviation_ids, milestone_ids
from sdd.parse.md import github_slug, id_slug, inline_children
from tests.spec03.helpers import found, parse_style, refs, targets


def test_spec03_ac03_reference_grammar() -> None:
    assert targets("SPEC-19 §4–§6") == ["SPEC-19#4", "SPEC-19#5", "SPEC-19#6"]
    assert targets("SPEC-02 §3–4") == ["SPEC-02#3", "SPEC-02#4"]
    assert targets("see SPEC-3 §4.6–4.7.") == ["SPEC-03#4.6", "SPEC-03#4.7"]

    (step,) = refs("SPEC-06 §7 step 1")
    assert (step.kind, step.target, step.note) == ("section", "SPEC-06#7", "step 1")

    (slug,) = refs("SPEC-02 `file_shares`")
    assert (slug.kind, slug.target, slug.slug) == ("slug", "SPEC-02", "file_shares")
    catalog = Catalog.from_results(parse_style("suite_style").values())
    assert resolve(slug, catalog).targets == ["SPEC-02#file_shares"]
    assert resolve(slug, catalog).unresolved == []
    missing = resolve(Ref("slug", "SPEC-02", 1, slug="nope"), catalog)
    assert missing.targets == []
    assert missing.unresolved == ["SPEC-02 `nope`"]


def test_spec03_ac04_text_beats_anchor() -> None:
    md = "[SPEC-02 §3–4](../specs/SPEC-02-x.md#3-chunks)"
    assert targets(md) == ["SPEC-02#3", "SPEC-02#4"]
    assert all(r.kind == "section" for r in refs(md))


def test_numbered_slug_section_resolves_through_title() -> None:
    catalog = Catalog.from_results(parse_style("rag_style").values())
    (ref,) = refs("SPEC-02 `documents`")
    assert resolve(ref, catalog).targets == ["SPEC-02#2"]


def test_part_list_stops_at_next_spec() -> None:
    assert targets("SPEC-25 §3, §6, SPEC-20 §13") == ["SPEC-25#3", "SPEC-25#6", "SPEC-20#13"]
    assert targets("SPEC-04 §1–3 and §7") == ["SPEC-04#1", "SPEC-04#2", "SPEC-04#3", "SPEC-04#7"]


def test_code_span_rule() -> None:
    assert targets("`SPEC-03 §5` is shown as an example") == []
    assert targets("```\nSPEC-03 §5\n```\n") == []
    assert targets("SPEC-02 `file_shares` and `SPEC-09 §1`") == ["SPEC-02"]
    assert targets("see `SPEC-09` and SPEC-02 §3") == ["SPEC-02#3"]
    assert deviation_ids(inline_children("`D018` and D019")) == ["D019"]
    assert backticked(inline_children("`brews` and `a b` and `-x`")) == ["brews"]


def test_whole_file_inside_and_after_link() -> None:
    (a,) = refs("[SPEC-03 (whole file)](../specs/SPEC-03-x.md)")
    assert (a.kind, a.target, a.whole) == ("spec", "SPEC-03", True)
    (b,) = refs("[SPEC-18](../specs/SPEC-18-x.md) (whole file)")
    assert (b.kind, b.target, b.whole) == ("spec", "SPEC-18", True)
    (c,) = refs("[SPEC-18 §5](../specs/SPEC-18-x.md) (whole section)")
    assert (c.target, c.whole, c.note) == ("SPEC-18#5", False, None)
    (d,) = refs("SPEC-04")
    assert (d.kind, d.whole) == ("spec", False)


def test_notes() -> None:
    (a,) = refs("[SPEC-00 §6 conventions](../specs/SPEC-00-x.md#6)")
    assert (a.target, a.note) == ("SPEC-00#6", "conventions")
    (b,) = refs("SPEC-18 §2.4 (streaming)")
    assert b.note == "streaming"
    (c,) = refs("see SPEC-06 §7 (the download exemption).")
    assert c.note == "the download exemption"
    (d,) = refs("SPEC-06 §7 (after M02.1)")
    assert d.note is None
    # one note applies to every Ref of the expression
    assert [r.note for r in refs("SPEC-02 §3–4 step 2")] == ["step 2", "step 2"]


def test_bare_section_link_takes_spec_from_target() -> None:
    assert targets("[§2.4](SPEC-18-x.md#24-streaming) (streaming)", "docs/specs/SPEC-06-y.md") == [
        "SPEC-18#2.4"
    ]
    assert targets("[§4.2](#42-task-ids)", "docs/specs/SPEC-04-sync.md") == ["SPEC-04#4.2"]
    (r,) = refs("[§2](../notes.md)", "docs/milestones/M01-x.md")
    assert r.kind == "path"


def test_plain_links_become_path_refs() -> None:
    (r,) = refs("[the spec](../specs/SPEC-03-x.md#5-foo)", "docs/milestones/M01-x.md")
    assert (r.kind, r.target, r.anchor) == ("path", "docs/specs/SPEC-03-x.md", "5-foo")
    (s,) = refs("[x](./a%20b.md)", "docs/y.md")
    assert s.target == "docs/a b.md"
    (t,) = refs("[x](#section)", "docs/y.md")
    assert (t.target, t.anchor) == ("docs/y.md", "section")
    (u,) = refs("[x](../../../out.md)", "docs/y.md")
    assert u.target.startswith("../")


def test_external_links_are_ignored() -> None:
    assert refs("[SPEC-03 §5](https://example.com/x) and [m](mailto:a@b.c) [x](//cdn/y)") == []


def test_ref_bad_range() -> None:
    (f,) = found("SPEC-02 §4.6–5")
    assert [w.code for w in f.warnings] == ["ref_bad_range"]
    assert [r.target for r in f.refs] == ["SPEC-02#4.6", "SPEC-02#5"]
    (g,) = found("SPEC-02 §6–3")
    assert [w.code for w in g.warnings] == ["ref_bad_range"]
    assert expand_range("SPEC-02", "1", "99") is None
    assert expand_range("SPEC-02", "4.6", "4.8") == ["SPEC-02#4.6", "SPEC-02#4.7", "SPEC-02#4.8"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SPEC-03 §10 checks 3–9, 12", (3, 4, 5, 6, 7, 8, 9, 12)),
        ("SPEC-03 §10 check 6", (6,)),
        ("[SPEC-03 §10](x.md) checks 1, 3", (1, 3)),
        ("SPEC-03 §10 checks 1–6 and 8", (1, 2, 3, 4, 5, 6, 8)),
        ("[SPEC-03 §10 checks 2–3](x.md)", (2, 3)),
    ],
)
def test_check_numbers(text: str, expected: tuple[int, ...]) -> None:
    (f,) = found(text)
    assert f.checks == expected
    assert f.spec == "SPEC-03"
    assert all(r.note is None for r in f.refs)


def test_doc_refs() -> None:
    (r,) = refs("see design-system §1, §2")
    assert (r.kind, r.target, r.note) == ("doc", "design-system", "§1, §2")
    (s,) = refs("[IDEA §3](../IDEA.md#3-x)")
    assert (s.kind, s.target) == ("doc", "IDEA")


def test_other_mentions() -> None:
    kids = inline_children("D018, [see](../deviations/D021-x.md), M02 and M02.3, [M20f](M20f-y.md)")
    assert deviation_ids(kids) == ["D018", "D021"]
    assert milestone_ids(kids) == ["M02", "M20f"]


def test_resolver_paths_anchors_and_moved_files() -> None:
    catalog = Catalog.from_results(parse_style("suite_style").values())
    spec = "docs/specs/SPEC-18-attachments.md"
    assert resolve(Ref("path", spec, 1), catalog).targets == ["SPEC-18"]
    hit = resolve(Ref("path", spec, 1, anchor="5-sharing"), catalog)
    assert hit.targets == ["SPEC-18#5"]
    assert hit.unresolved == []
    miss = resolve(Ref("path", spec, 1, anchor="nope"), catalog)
    assert miss.targets == ["SPEC-18"]
    assert miss.unresolved == [f"{spec}#nope"]
    here = resolve(Ref("path", "docs/milestones/M17-photo-attachments.md", 1), catalog)
    assert here.targets == ["M17"]
    assert here.warnings == []
    moved = resolve(
        Ref("path", "docs/milestones/done/M17-photo-attachments.md", 3), catalog, path="a.md"
    )
    assert moved.targets == ["M17"]
    assert [(w.code, w.severity) for w in moved.warnings] == [("link_moved", "info")]
    gone = resolve(Ref("path", "docs/nothing.md", 1), catalog)
    assert gone.targets == []
    assert gone.unresolved == ["docs/nothing.md"]
    assert resolve(Ref("doc", "design-system", 1), catalog).targets == ["doc:docs/design-system.md"]
    assert resolve(Ref("doc", "HANDOFF", 1), catalog).unresolved == ["HANDOFF"]
    assert resolve(Ref("mention", "x", 1), catalog).targets == []


def test_github_slug() -> None:
    assert github_slug("13. Table → milestone map") == "13-table--milestone-map"
    assert github_slug("2. documents") == "2-documents"
    assert github_slug("5.2 Chunking") == "52-chunking"
    assert github_slug("Identity (SPEC-03)") == "identity-spec-03"


def test_id_slug_round_trips() -> None:
    for title in ("file_shares", "`documents`", "Table → milestone map", "2024", "ac3", "???"):
        slug = id_slug(title)
        assert normalise(f"SPEC-02#{slug}") == f"SPEC-02#{slug}"
    assert id_slug("`documents`") == "documents"
