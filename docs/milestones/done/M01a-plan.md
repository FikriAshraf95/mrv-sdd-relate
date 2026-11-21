# M01a implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-03 (whole file)](../../specs/SPEC-03-markdown-parsing.md), [SPEC-02 §1–2](../../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties) and [§4](../../specs/SPEC-02-graph-schema.md#4-relationships), [SPEC-10 §1, §3](../../specs/SPEC-10-testing-and-benchmark.md#3-fixtures), [SPEC-00 §6](../../specs/SPEC-00-overview.md#6-global-conventions). Milestone: [M01a](M01a-markdown-parsers.md).
Follow `CLAUDE.md`. Any knowing departure from a spec → `docs/deviations/D002-….md` (D001 is the highest so far) + index row + spec note, in the same change. If the spec is merely silent, decide, write it down in the spec (or here), and say so in the report.

## 0. Scope and boundaries

- **Pure parsers only.** `src/sdd/parse/` may import stdlib, `markdown_it`, `sdd.ids`, `sdd.errors` (import-linter contract already exists). No file I/O, no `config`, no graph. Text in, `ParseResult` out. Parsers **never raise** on bad Markdown; anything odd is a warning.
- `graph/` may not import `parse/` (contract). So parsed output is **generic** (`Node`, `Rel` with plain `dict` props and string IDs), which M01b's `sync/indexer.py` can hand to `graph/upsert.py` as plain data.
- Not in M01a: schema tables (§6, M04b), Feature/Domain nodes (M04b; M01a only extracts the Feature line into a record), MENTIONS resolution, upsert, file globbing, `sdd doctor`.
- Normalise `\r\n` / `\r` to `\n` at the start of every parser (line numbers unchanged).

## 1. Module layout

```
src/sdd/parse/
  __init__.py      re-exports the public API below
  model.py         Node, Rel, Ref, ParseWarning, ParseResult, FeatureLine, IndexRow, Severity
  md.py            one shared MarkdownIt("commonmark") instance (tables enabled: .enable("table")),
                   helpers: tokens(text), inline(text), heading_text(inline_token), github_slug(), id_slug(),
                   content_hash(text) (sha256 hex of the UTF-8 text)
  links.py         reference extraction (§3 below) and the pure resolver
  specs.py         parse_spec(path, text) -> ParseResult
  milestones.py    parse_milestone(path, text) -> ParseResult
  deviations.py    parse_deviation(path, text), parse_deviation_index(path, text), cross_check_index(...)
  docs.py          parse_doc(path, text), parse_plan(path, text)
```

`path` is always the project-relative POSIX path (`docs/specs/SPEC-03-x.md`).

## 2. Data model (`model.py`)

All frozen dataclasses (slots), fully typed for `mypy --strict`.

```python
Severity = Literal["info", "warning", "error"]

@dataclass(frozen=True, slots=True)
class ParseWarning:
    path: str; line: int; code: str; message: str; severity: Severity = "warning"

@dataclass(frozen=True, slots=True)
class Ref:
    """An unresolved relationship target, resolved later against the graph (M01b) or a Catalog."""
    kind: Literal["id", "section", "slug", "spec", "path", "doc", "mention"]
    target: str            # id: any canonical ID ("M02", "M02.3", "D018", "SPEC-02#3", "doc:x")
                           # section: "SPEC-02#3"  slug: "SPEC-02" (slug in .slug)  spec: "SPEC-03"
                           # path: resolved project-relative path  doc: "design-system"  mention: raw identifier
    line: int
    anchor: str | None = None   # path refs only (no '#')
    slug: str | None = None     # slug refs only
    whole: bool = False         # "(whole file)" on a spec ref
    note: str | None = None     # trailing words: "step 1", "streaming", "conventions"
    text: str = ""              # the raw matched text, for warnings and doctor

@dataclass(frozen=True, slots=True)
class Node:
    label: str             # a SPEC-02 label
    id: str                # canonical ID (ids.normalise round-trips it)
    props: dict[str, Any]  # SPEC-02 properties + source_path, source_line, content_hash; NO last_synced

@dataclass(frozen=True, slots=True)
class Rel:
    type: str              # a SPEC-02 §4 type
    from_id: str           # canonical ID; may name a node in another file (AMENDS from D018, reversed Blocks)
    to: Ref
    props: dict[str, Any] = field(default_factory=dict)   # note / whole copied from Ref, check numbers…

@dataclass(slots=True)
class ParseResult:
    path: str
    nodes: list[Node]
    rels: list[Rel]
    warnings: list[ParseWarning]
    features: list[FeatureLine] = field(default_factory=list)   # specs only, raw (M04b makes nodes)
```

`src` on relationships is **not** set by the parser; M01b sets `src = result.path`. Relationship props hold only what SPEC-02 says (`note`, `whole`, and for VERIFIES nothing extra — one Rel per check).

`FeatureLine`: `line, raw, name, slug, domain (str|None), domain_slug, implements: tuple[str,...]` (globs, backticks stripped), `tables: tuple[str,...]`.
`IndexRow`: `line, id, link_path (str|None), title, milestone, spec, status` (raw cell text).

## 3. `links.py` — references (SPEC-03 §1 rule 5, §2)

### 3.1 Entry points
```python
def refs_in_inline(children: list[Token], *, path: str, line: int) -> list[Found]
def refs_in_markdown(md_text: str, *, path: str, line: int) -> list[Found]   # md.parseInline wrapper
def resolve(ref: Ref, catalog: Catalog) -> Resolution                        # pure
def expand_range(spec_id, start, end) -> list[str] | None                    # numeric sibling expansion
```
`Found` = `Ref` + `start`/`end` char offsets in the plain-text rendering + optional `checks: tuple[int,...]` (§3.5) + warnings. Callers map Found → Rel of the right type.

### 3.2 Walking inline tokens (the code-span rule)
Build a plain-text rendering of the inline children with a parallel "region" map:
- `text` → copied; `softbreak`/`hardbreak` → `\n` (count them to get each ref's line = paragraph start line + newlines before it).
- `code_inline` → rendered as `` `content` ``, marked **code**. A match whose `SPEC-` (or `M02.3`, `[Dnnn]`, `**DEVIATION:**`) starts inside a code region is ignored. The only code region a match may contain is a whole backticked `part` identifier (§2.2).
- `link_open … link_close` → one **link atom** (href + link text rendered the same way). Refs inside link text belong to the link; the plain-text scan does not see them again.
- Fenced and indented code blocks never reach here (they are `fence`/`code_block` tokens, not `inline`). Callers skip them, and also skip `html_block`.

### 3.3 Grammar (one compiled regex set, used everywhere)
```
ref     := "SPEC-" digits [ ws? sections ] [ ws? ( "(whole file)" | "(whole section)" ) ]
sections:= part ( ws? ("," | "and") ws? part )*
part    := "§" ws? num [ ws? ("–"|"-") ws? "§"? num ]  |  "`" identifier "`"
num     := digits ("." digits)*
```
- Spec numbers pad through `ids.normalise` (`SPEC-3` → `SPEC-03`).
- A `part` list stops at the first thing that is not a part (`SPEC-25 §3, §6, SPEC-20 §13` = two refs).
- `num` loses a trailing `.` (sentence end: "see SPEC-03 §4.").
- **Ranges** (`expand_range`, numeric, no catalog needed): both ends must have the same parent prefix and integer last components: `§3–4` → 3, 4; `§4.6–4.7`; `§4–§6` → 4, 5, 6. Anything else (`§4.6–5`, start > end, > 50 items) → keep both ends as plain section refs + `ref_bad_range` warning. M01b drops expanded IDs that do not exist as unresolved, like any other.
- `(whole file)` → one `spec` Ref with `whole=True`. `(whole section)` = no suffix. Suffix may be inside the link text or directly after the link (`[SPEC-18 §5](…) (whole section)`).
- `SPEC-NN` with no sections → `spec` Ref.
- Backticked part → `slug` Ref (`target=spec`, `slug=identifier`).
- **Note**: the trailing words of the ref, taken from (a) the rest of the link text after the ref (`[SPEC-00 §6 conventions](…)` → `conventions`), (b) a parenthetical directly after the ref or link (`(streaming)`, `(the download exemption)`), excluding the whole-suffixes, (c) `step|invariant|item|rule|case|row` + number directly after (`SPEC-06 §7 step 1` → `step 1`). Strip, collapse spaces, cap at 120 chars. A note applies to every Ref produced by that ref expression.
- **Non-spec doc refs** (§2.2 last bullet): `design-system §1, §2`, `IDEA §3`, `HANDOFF §2`: regex for the known doc stems `design-system|IDEA|HANDOFF|README|CLAUDE` followed by `§`… → one `doc` Ref (`target` = stem, `note` = the § text). Keep the list as a module constant.

### 3.4 Links (§2.1)
- `http:`, `https:`, `mailto:`, `//…` → ignored (no refs, even from the text).
- Relative href → split `path#anchor`, URL-unquote, resolve against `posixpath.dirname(path)` with `posixpath.normpath`. Anchor-only (`#42-task-ids`) → the current file. A path escaping the root stays as-is (it will be unresolved).
- If the link text contains spec refs → **the text wins** (§2.2): emit those refs, not the anchor.
  - If the link text has `§` parts but no `SPEC-` prefix (`[§2.4](SPEC-18-x.md#24-…)`, `[§4.2](#42-task-ids)`), take the spec ID from the target file name (`ids.id_from_filename`). If the target is not a spec file, fall through to a path ref.
- Otherwise → one `path` Ref (`target` = resolved path, `anchor`).
- `checks` lookahead (§3.5) and the whole-suffix / parenthetical note lookahead also run on the text right after a link.

### 3.5 Acceptance-check numbers (for VERIFIES)
Right after a ref (or after its link), `checks?` + number list: `checks 3–9, 12`, `check 6`, `checks 1, 3`, `checks 1–6 and 8`. Ranges expand (cap 100). Stored on `Found.checks`. Only the milestone parser uses it (Task → `<spec>#ac<n>`; spec = the ref's spec ID).

### 3.6 Other mentions found by the same walk (all honour the code-span rule)
- `deviation_ids(...)`: `\bD\d{3,}\b` (and `[D018](…)` links) → normalised IDs.
- `milestone_ids(...)`: `\bM\d+[a-z]?\b` not followed by `.\d` → milestone mentions; links whose target file name is a milestone file count too.
- `backticked(...)`: identifiers in `code_inline` that look like a table name or a path (`^[A-Za-z0-9_./-]+$`, not starting with `-`) → `mention` Refs (MENTIONS candidates; M01b/M04b keep only exact table/file matches and drop the rest **silently**, not as unresolved).

### 3.7 Resolver (pure; used by M01b, tested here)
```python
@dataclass
class Catalog:
    paths: dict[str, str]                 # source_path -> node id (Spec, Milestone, Deviation, Doc)
    ids: set[str]                         # every known node id
    anchors: dict[str, dict[str, str]]    # spec_id -> {github anchor -> section id}
    slugs: dict[str, dict[str, str]]      # spec_id -> {title slug -> section id} (numbered or not)
    docs: dict[str, str]                  # doc stem ("design-system") -> doc id
Resolution = (targets: list[str], unresolved: list[str], warnings: list[ParseWarning])
```
- `id`/`section`/`spec`: present in `ids` → target, else unresolved.
- `slug`: `slugs[spec][id_slug(slug)]`, else unresolved.
- `path`: `paths[target]`; with an anchor on a spec, `anchors[spec][anchor]` (anchor miss → the Spec node + unresolved anchor string). **Moved files**: no such path but the file name starts with a spec/milestone/deviation ID (`ids.id_from_filename`) and that ID is in `ids` → that node, plus `link_moved` (severity `info`).
- `doc`: `docs[stem]`, else unresolved. `mention`: never resolved here (M01b/M04b).
- Unresolved strings are human-readable: `SPEC-02#9`, `` SPEC-02 `file_share` ``, `docs/x.md#anchor`.
A helper `Catalog.from_results(results: Iterable[ParseResult])` builds a catalog from parsed specs/milestones/deviations/docs, so tests (and M01b's doctor) can resolve without a graph.

## 4. Shared heading rules (`md.py`)

- `heading_text`: render the heading's inline children as plain text (code spans lose backticks, link text kept, emphasis dropped).
- Number: `^(\d+(?:\.\d+)*)\.?\s+(.+)$` → `number`, `title`. `## 6. Global conventions` → `6`; `### 5.2 Chunking` → `5.2`; `## 10. X` → `10`.
- `github_slug(text)`: GitHub rules on the full heading text: lower-case; drop every char that is not a Unicode letter/number, `_`, `-` or space; spaces → `-`. Duplicates within a file get `-1`, `-2` (GitHub style). `13. Table → milestone map` → `13-table--milestone-map`; ``2. `documents` `` → `2-documents`.
- `id_slug(title)`: our ID slug (SPEC-02 §1): lower-case, backticks stripped, runs of chars outside `[a-z0-9_]` → `-`, trimmed of `-`. Dedupe within a spec with `-2`, `-3`. Must round-trip through `ids.normalise`.

## 5. `specs.py` (SPEC-03 §3)

Input path's file name gives the ID (`ids.id_from_filename`); none → `bad_filename` error and an empty result.
- **H1** `# SPEC-NN — Title` (em/en dash or hyphen): `title`. Missing H1 → `missing_h1` warning, title = file stem. ID in H1 ≠ file ID → `h1_id_mismatch` warning (file wins).
- **Header**: the first blockquote after the H1 (before any other block except blank lines). Work on its raw source lines (strip `>` markers, keep line numbers). Split pairs on `**Key:**`; split on ` · `; a piece without a `**Key:**` start continues the previous key's value (so multi-line and multi-ref values stay together). `header` = `{key: value}` with key text as written (`Status`, `Owner of`, `Spec ID`, `Consumed by`, `Feature`…), values trimmed, newlines collapsed to spaces. `status` = header `Status`, `owner_of` = header `Owner of` (else null). Feature lines are **not** put in `header` (several per spec); they go to `features`.
- **Feature line** (§3.3): a header line starting `**Feature:**`. Split on ` · ` into `Feature`, `Domain`, `Implements`, `Tables`. Globs: backticked, comma-separated. Tables: comma-separated, backticks stripped. Missing name → `feature_bad_line` warning. Slugs via `id_slug` with `_`→`-` (`file-sharing`).
- **Sections**: every H2–H4 `heading_open` token (never inside code). Props per SPEC-02 §2 `Section`: `spec_id, number, title, anchor, level, line_start, line_end, text` + `source_path, source_line (= line_start), content_hash`. ID `SPEC-NN#<number>` or `SPEC-NN#<id_slug>`; duplicate IDs get `-2`… with `section_duplicate_id` (info). `changed_at` is sync's job (do not set).
  - `text` = raw source lines after the heading up to (not including) the next H2–H4 heading of **any** level (children are their own nodes), trimmed of blank lines at both ends. `line_end` = last line of that range (inclusive), so a parent's range does not cover its children. Hash covers `text` only.
  - `HAS_SECTION`: Spec → each H2; each H3/H4 → from the nearest shallower section above (an H4 directly under an H2 hangs from the H2). Rels use `Ref(kind="id")`.
  - Preamble (between header and first H2) and the header produce no relationships (SPEC-02 §4 has LINKS_TO only from Section).
- **LINKS_TO**: every Found ref in the section's own inline tokens (paragraphs, list items, tables, blockquotes at any depth; not code) → `Rel("LINKS_TO", section_id, ref, {note?})`. Skip refs that point at the section itself.
- **MENTIONS candidates**: backticked identifiers in the section's own text → `Rel("MENTIONS", section_id, Ref(kind="mention"))`, deduped per section.
- **DEVIATION notes**: an `inline` token (any blockquote depth, inside list items too) whose text contains `**DEVIATION:**` (rendered as `strong` with text `DEVIATION:` — check the token stream, not raw text, so code is excluded) → for every `Dnnn` link/mention on that line: `Rel("AMENDS", "D018", Ref(kind="id", target=section_id))`. A note before the first H2 amends the Spec.
- **Acceptance checks**: a section whose title (case-insensitive, number stripped) is `Acceptance checks` → one `AcceptanceCheck` per **top-level** ordered-list item of that section: `id = SPEC-NN#ac<n>` where n = the item's own number (`token.info` on `list_item_open`, else the running count), props `spec_id, number, text` (raw item lines, continuation included, marker stripped) + common props. `HAS_CHECK` Spec → check. Duplicate number → `ac_duplicate_number` warning, second skipped.
- **Spec node** props: `title, status, owner_of, header` (a dict; store.py encodes it) + `source_path, source_line=1, content_hash` (whole text).

## 6. `milestones.py` (SPEC-03 §4)

ID from file name (`M02`, `M20f`, `M100`). `order` = zero-padded number to 4 + suffix (`0002`, `0020f`, `0100`). `path` = the input path.
- **H1** `# M02 — Title` → `title` (same `missing_h1` / `h1_id_mismatch` rules).
- **Header** blockquote: same splitter as specs. `header` keeps every pair.
  - `Depends on` → `DEPENDS_ON` (this → each milestone linked or named in the segment, via link targets' file-name IDs and `milestone_ids`). Value `—`, `-`, `nothing`, `none` (case-insensitive, after stripping) → none. `Blocks` → `Rel("DEPENDS_ON", other, Ref(id=this))`. Duplicates merge (dedupe Rels by (type, from, target)). `nothing directly` → none (any milestone ID-free value yields none, no warning).
  - `Read first` → `READS` for every spec Ref in the segment (sections, slugs, specs with `whole`). Doc refs and non-spec links (`[DEVIATIONS](../DEVIATIONS.md)`) are also READS? **No**: SPEC-02 §4 says READS → Section | Spec only, so non-spec targets are dropped without warning.
  - `Model` → `model` = first word if it is `Opus`, `Sonnet`, `Opusplan`, `Haiku` (trailing `.`/`,` stripped), else null; the full text stays in `header`.
- **Sections**: H2/H3 found by title (case-insensitive): `Goal` → `goal` (raw text, trimmed); `Acceptance criteria` → `acceptance: list[str]` (top-level numbered items, continuation lines joined); `Checks finished in later milestones` → `header["later_checks"]` raw text.
- **Tasks** (§4.2): from the token stream, every `list_item_open` whose first inline starts with `[ ] `, `[x] `, `[X] ` (markdown-it keeps it as text). Use the regex from §4.2 on the item's first source line to get the ID.
  - `checked`, `title` (text after the ID/markers, **links rendered as their text**, continuation lines and nested plain bullets included, joined with single spaces / newlines kept for nested bullets; nested checkbox items excluded — they are their own tasks), `group` = text of the nearest preceding H3 (null if none), `order` = 1-based position in the file, `milestone_id`, `stable_id`, `source_line`, `content_hash` (of the raw item text). **No `status` prop**: derived by upsert (SPEC-02 §2 Task).
  - ID milestone part ≠ file's milestone → `task_id_mismatch` warning, keep the ID as written (normalised).
  - **Legacy** (no `**Mxx.n**`): ID `<milestone>.p<order>`, `stable_id=false`, `task_unstable_id` warning. Note: `ids.normalise` does not accept `.p3` — do not route positional IDs through it.
  - Duplicate stable ID in a file → `task_duplicate_id` **error**; the second becomes positional.
  - `(after M02.1, M01.4)` at the end of the title → `BLOCKED_BY` Refs (`kind="id"`), removed from `title`. A token that is not a task ID → `task_bad_after` warning.
  - Refs in the task text → `GOVERNED_BY` (spec/section/slug refs only, like READS). `checks …` after a ref → one `VERIFIES` per check `SPEC-NN#ac<n>`. MENTIONS candidates as for sections.
  - `INCLUDES` Milestone → Task.
- **Status** (§4.4): the paragraph whose rendered text starts with `Status:` inside a leading `strong` (covers `**Status:** …` and `**Status: DONE (…), with …**`). `status_text` = raw source of that paragraph plus any directly following list (bullets) — null if absent, `""`-only → null.
  - `DONE` case-insensitive at its start (after `Status:`) → `status = "done"`, `done_date` from the first `(YYYY-MM-DD)`. Otherwise `status = "in_progress"` if any task is `checked`, else `"todo"` (claims are graph-only; upsert recomputes with claims).
  - Deviation IDs in the status text → `Rel("RAISED_IN", "D021", Ref(id=this milestone))`.
- **Milestone node** props: `title, order, status, status_text, done_date, model, goal, acceptance, path, header` + common.

## 7. `deviations.py` and `docs.py` (SPEC-03 §5)

**parse_deviation**: ID from file name; H1 `# D012 — Title` → `title`. Bullet fields (top-level list before the first H2): `**Date / milestone:**`, `**Spec:**`, `**Affects:**`, `**Status:**`.
- Date/milestone: split on `·`: first part a date `YYYY-MM-DD` → `date`; then a milestone ID → `RAISED_IN` → Ref(id=milestone); then an optional task ID → `RAISED_IN` → Ref(id=task). A part that is not an ID (e.g. `UI refresh`) is kept in raw `header`-like prop `milestone_text`, no warning. Unparsable date → `deviation_bad_field` warning, `date = null`.
- Spec: every ref via links.py → `AMENDS` (spec/section/slug/doc refs; notes kept: `SPEC-06 §7 step 1` → `SPEC-06#7`, note `step 1`).
- Affects: backticked entries, comma-separated → `Rel("AFFECTS", id, Ref(kind="mention", target=entry))` (M01b/M04b resolve to File/Table or unresolved; here they are `mention` refs but **kept as unresolved** when they don't match — say so in the Rel props: `{"strict": True}`).
- Status: `status_text` raw; `status = "resolved"` if it starts with `Resolved`, else `"open"`.
- H2 sections `Spec says`, `Implementation does`, `Why`, `Consequences` → `spec_says, implementation_does, why, consequences` (raw text, trimmed); a missing one → `deviation_missing_section` warning (value `""`).
- MENTIONS candidates from the whole body.

**parse_deviation_index** → `list[IndexRow]` (+ warnings) from every Markdown table row (token stream, so the template inside a code fence is ignored) whose first cell contains a `D\d+` ID (linked or plain). Placeholder rows (`—`) skipped. Returns a `ParseResult` with no nodes and the rows on a field `index_rows` (add it to `ParseResult`, default empty).
**cross_check_index(index_rows, deviation_paths: dict[str, str], index_path) -> list[ParseWarning]**: file without row, row without file → `deviation_index_mismatch` (warning), at the row's line or line 1.

**parse_doc**: `Doc` node, `id = "doc:" + path`, `kind` from the file name (`CLAUDE.md` → `claude_md`, `IDEA.md` → `idea`, `design-system.md` → `design_system`, `HANDOFF.md` → `handoff`, `README.md` → `readme`, else `other`), `title` = H1 text or file name, `path`, common props. Every ref in the doc (whole document, not code) → `LINKS_TO` from the Doc. *(SPEC-02 §4 lists LINKS_TO from Section only, but SPEC-03 §5.3 says docs' links become LINKS_TO: add `Doc` to the `LINKS_TO` From column in SPEC-02 §4 in this change — a spec fix, not a deviation.)*
**parse_plan**: as a doc with `kind = "plan"` and `Rel("PLANS", doc_id, Ref(id=<milestone from file name>))`.

## 8. Warning codes (add this table to SPEC-03 §1 in this change)

| Code | Severity | When |
|---|---|---|
| `bad_filename` | error | the file name has no Spec/Milestone/Deviation ID (parser cannot build the node) |
| `task_duplicate_id` | error | two tasks with the same stable ID in one file |
| `missing_h1` | warning | no H1 |
| `h1_id_mismatch` | warning | the H1's ID differs from the file name's |
| `task_id_mismatch` | warning | §4.2 |
| `task_unstable_id` | warning | §4.2 |
| `task_bad_after` | warning | `(after …)` names something that is not a task ID |
| `ref_bad_range` | warning | a § range that cannot be expanded |
| `ac_duplicate_number` | warning | two acceptance checks with one number |
| `feature_bad_line` | warning | a Feature line without a name |
| `deviation_missing_section` | warning | §5.1 |
| `deviation_bad_field` | warning | an unparsable date |
| `deviation_index_mismatch` | warning | §5.2 |
| `section_duplicate_id` | info | two headings map to one ID (deduped) |
| `link_moved` | info | §2.1 (resolver) |

Severity order matters for `sdd doctor` (exit 1 on `error`). Keep the codes in one `frozenset`/dict in `model.py` (`WARNING_CODES: dict[str, Severity]`) and build every warning through a helper that looks the severity up, so a typo fails fast in tests.

## 9. Fixtures (M01a.1) — invented content only

**Never copy text, titles, file names (beyond ID + invented slug), commit messages or table rows from `/refs/office-suite` (office-suite-v2) — O1.** Do not copy office-rag text either; reproduce conventions only. Use invented domains:

- `tests/fixtures/rag_style/` — office-rag conventions, domain: **a community library lending app**.
  - `CLAUDE.md` (root) + `backend/CLAUDE.md` (nested), `docs/IDEA.md`, `docs/design-system.md`.
  - `docs/specs/SPEC-00-overview.md`: `**Status:** v1 (…) · **Owner of:** …` header + `> **Read with:** [IDEA](../IDEA.md)`; `## 6. Global conventions` with `### 6.1 …`, `### 6.2 …`; an `## 8. Acceptance checks` list.
  - `docs/specs/SPEC-02-database-schema.md`: `## 1. Extensions`, `` ## 2. `documents` ``, `` ## 3. `loans` ``, `` ## 4. `jobs` ``, each with a `| Column | Type | Rules |` table (keep for M04b); `## 7. Table → milestone map`; acceptance checks.
  - Minimal `SPEC-03-…`, `SPEC-06-…` (with §2, §4, §5, §6), `SPEC-08-…` (with `### 4.6`, `### 4.7`), `SPEC-11-…` (§2) so links resolve.
  - `docs/milestones/M00-foundation.md` and `M02-ingestion.md` in the office-rag task style: **tasks without IDs** (legacy), `### Backend/Frontend/Tests` groups, `## Goal`, `## Acceptance criteria`, `**Status:**` empty. **M02's Read first must be exactly this shape** (invented anchors/slugs fine):
    `> **Read first:** [SPEC-03 (whole file)](../../specs/SPEC-03-….md) · [SPEC-02 §3–4](../../specs/SPEC-02-database-schema.md#3-loans) · [SPEC-06 §2, §4–6](../../specs/SPEC-06-….md#2-…) · [SPEC-08 §4.6–4.7](../../specs/SPEC-08-….md#46-…) · [SPEC-11 §2](../../specs/SPEC-11-….md#2-…)`
    plus a test line like `- [ ] SPEC-03 §10 checks 3–9, 12 (…)`.
  - `docs/DEVIATIONS.md` with the rules, a fenced template containing `# D<nnn> — <title>` and a `` `> **DEVIATION:** see [D<nnn>](…)` `` inline-code example (must yield nothing), an empty index table; `docs/deviations/` empty (`.gitkeep`).
- `tests/fixtures/suite_style/` — office-suite-v2 conventions, domain: **a plant nursery stock app** (invent every word).
  - `docs/specs/SPEC-02-database-schema.md`: `> **Spec ID:** SPEC-02 · **Consumed by:** …` + `> **Related:** [SPEC-00 §6 conventions](SPEC-00-overview.md#6-…)`; `## 1. Identity ([SPEC-03](SPEC-03-….md))` with `### users`, `## 2. Files ([SPEC-18](…))` with `### attachments` (`| Column | Type | Notes |`, a row `| uploaded_by | uuid not null | → users [restrict] |`, a `ts` column) and `### file_shares`; a `## 13. Table → milestone map`. Include a nested `> > **DEVIATION:** see [D018](../deviations/D018-….md) — …` under one section and an indented-in-list `  > **DEVIATION:** see [D012](…)` under another.
  - Minimal `SPEC-00`, `SPEC-03`, `SPEC-06` (with `## 7.`), `SPEC-18` (with `## 5.`, `### 2.4`, `## 6. Acceptance checks`).
  - `docs/milestones/M17-<invented>.md`: multi-line Read first like `[SPEC-18 §5](…) (whole section) and` / `> [§2.4](…) (streaming) →` / `` > [SPEC-02 `file_shares`](…#file_shares) · ``; `**Depends on:** [M02](M02-….md) technically (scheduled after [M16](M16-….md)) · **Blocks:** nothing directly`; legacy `- [x]` tasks with continuation lines and nested plain bullets; a test line `- [x] [SPEC-18 §6](…) 6.`; `**Status: DONE (2026-11-01), with one open item.** … Deviations: [D021](../deviations/D021-….md).` followed by bullets.
  - Letter-suffixed `M20f-<invented>.md` and its `M20f-plan.md`; tiny `M02-…`, `M16-…` stubs.
  - `docs/deviations/D012-<invented>.md` with `**Spec:** SPEC-06 §7 step 1` (plain, unlinked) and `**Status:** Resolved → spec updated`; `D018-…`, `D021-…` with linked Spec fields; all without Affects/task (they must parse with **no warnings**). `docs/deviations/README.md` (not `D*.md`). `docs/DEVIATIONS.md` index rows `| [D021](deviations/D021-….md) | … | M17 | SPEC-18 §5 | Open |`, one row with Milestone `UI refresh` and Spec `design-system §1, §2` (add a D023 file for it).
- `tests/fixtures/tool_style/` — extend the docs part: SPEC-01 gets a header blockquote with a Feature line (`` > **Feature:** Brewing · **Domain:** Tea · **Implements:** `src/kettle/**` · **Tables:** brews, teas ``), a `## 3. Acceptance checks` list; M01 gets stable IDs, `(after …)`, a nested checkbox task, a `### Tests` group with `[SPEC-01 §3](…) checks 1–2 and 3`; add `M02-<x>.md` with one `**M01.4**` mismatch line (or put it in a separate fixture string inside the test, to keep the fixture clean); a deviation `D001-…` with `**Date / milestone:** 2026-11-02 · M01 · M01.2` and `` **Affects:** `src/kettle/brew.py`, `brews` ``, and its index row. Keep existing files' content working for the M00 tests (`tests/spec10/test_test_host.py` reads tool_style — re-run it).
- Update `tests/fixtures/README.md` (one line per fixture).

## 10. Tests (M01a.6) — `tests/spec03/`

Read fixtures with `Path.read_text(encoding="utf-8")` in the test (the parser stays pure). Assert on IDs and codes, never messages.
- `test_parse_links.py`: grammar unit tests, incl. **`test_spec03_ac03_reference_grammar`** (`SPEC-19 §4–§6` → 3 section refs; `SPEC-02 §3–4` → 2; `` SPEC-02 `file_shares` `` resolves through a Catalog built from the suite fixture's SPEC-02 to `SPEC-02#file_shares`; `SPEC-06 §7 step 1` → `SPEC-06#7`, note `step 1`) and **`test_spec03_ac04_text_beats_anchor`** (`[SPEC-02 §3–4](…#3-chunks)` → `#3` and `#4`). Plus: code-span rule (inline code, fenced, indented → no refs; the backticked `part` still works), `(whole file)` inside/after link, bare-§ link text taking the spec from the target, external links ignored, `ref_bad_range`, `checks 1–6 and 8`, doc refs, moved-file resolution with `link_moved` info, github_slug cases above, `SPEC-25 §3, §6, SPEC-20 §13`.
- `test_parse_specs.py`: both header styles; Feature line → **`test_spec03_ac08_feature_line_parse`** (name, slug `brewing`, domain `tea`, globs, tables; parse side only); sections/number/anchor/own-text hash (edit a child, parent hash unchanged); H4 under H2 nesting; duplicate slug dedupe; acceptance checks; **`test_spec03_ac06_nested_deviation_note`** (`> > **DEVIATION:** see [D018]` → `AMENDS` from `D018` to its section, and the in-list `  > **DEVIATION:**` too; the inline-code example in DEVIATIONS-style text yields none).
- `test_parse_milestones.py`: **`test_spec03_ac05_task_lines`** (`**M02.3**` stable; legacy `M17.p3` + `task_unstable_id`; `(after M02.1)` → BLOCKED_BY); continuation lines + nested bullets in title; nested checkbox own task; group; `task_id_mismatch`; `task_duplicate_id` error; VERIFIES; Blocks reversal; `nothing directly`; status variants (`**Status:**` empty → todo/in_progress, `DONE (date)`).
- `test_parse_fixtures.py`: **`test_spec03_ac01_rag_fixture`** (every rag_style doc parses with zero `error`; M02 READS targets == {`SPEC-03` whole, `SPEC-02#3`, `#4`, `SPEC-06#2`, `#4`, `#5`, `#6`, `SPEC-08#4.6`, `#4.7`, `SPEC-11#2`}) and **`test_spec03_ac02_suite_fixture`** (zero `error`; M17 `done`, `done_date == "2026-11-01"`, a `RAISED_IN` Rel from `D021` to `M17`); plus every fixture doc of all three styles through the matching parser with zero `error`, and a Catalog built from each fixture resolves every READS/GOVERNED_BY/AMENDS with zero unresolved (except deliberate ones you document in the test).
- `test_parse_deviations.py`: fields, task RAISED_IN, Affects refs, missing sections warning, `Resolved → spec updated` → resolved, a deviation without task/Affects → no warnings, index parse ignores the fenced template, `cross_check_index` both directions.
- `test_parse_docs.py`: kinds, plan PLANS, doc links.
- A property-ish robustness test: every parser on `""`, `"# \n"`, binary-ish garbage, an unclosed fence, a 5-level nested blockquote → no exception.
- Extend `tests/invariants/` only if trivial; invariant 6 (doc↔code drift) is later.

## 11. Order of work

1. `model.py`, `md.py` (+ tests for slugs/hash). 2. `links.py` + its tests. 3. Fixtures. 4. `specs.py`, 5. `milestones.py`, 6. `deviations.py` + `docs.py`, each with tests. 7. Fixture-level tests. 8. Spec edits: SPEC-03 §1 warning-code table; SPEC-02 §4 `LINKS_TO` from `Doc`. 9. Full gates. 10. Walkthrough (acceptance 2): a throwaway script **outside the repo** (scratch dir, or `/tmp` in the container) that globs `/refs/office-rag/docs`, `/refs/office-suite/docs` and `/workspace/docs` (+ CLAUDE.md files, HANDOFF, README; the refs mount only `docs/` and the root `CLAUDE.md`) by the SPEC-03 §1 defaults (milestones: name matches `M\d+[a-z]?-.+\.md` and not `-plan`), runs the right parser, runs `cross_check_index`, builds a Catalog per project and resolves every Rel, then prints **counts only**: per project, number of files per kind, warnings per code, unresolved count. Zero `error`. Do not print or save any reference text.

## 12. Gates and commit

Inside the dev container: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/sdd && uv run lint-imports && uv run pytest -q`. All green. Then tick M01a's boxes, fill **Status** (`DONE (date)`, how verified, walkthrough counts per code per project, deviations), move `M01a-markdown-parsers.md` and this plan to `docs/milestones/done/` (fix relative links in both: `../specs/` → `../../specs/`), update CLAUDE.md's status block (next: M01b). One commit `feat: markdown parsers [M01a]` with the attribution trailer. **Do not commit until the Opus review has passed** (the orchestrator commits).
