# M04a implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-04 §2, §4, §6](../specs/SPEC-04-sync.md#4-code-walker), [SPEC-02 §3–4, §7](../specs/SPEC-02-graph-schema.md#3-codebase-layer), [SPEC-03 §1](../specs/SPEC-03-markdown-parsing.md#1-rules-and-configuration). Milestone: [M04a](M04a-code-and-git.md). Previous plan: [M02-plan](done/M02-plan.md).
Follow `CLAUDE.md`. D005 is the highest deviation. This plan expects **no deviation**: each decision below fills a gap the spec leaves open, and is written into the owning spec in the same change (§9). If you knowingly depart from a spec anyway, call `log_deviation` (D006…).

## 0. Scope and boundaries

- **In:** `sync/files.py` (ignore rules, walker, code cache), `sync/git.py` (git reader, HEAD poller), `graph/code.py` (all code-layer Cypher), the indexer scoping fix (M04a.6), `sync/pipeline.py` (one sync order for startup, batches, HEAD changes and `sdd sync`), `service/runtime.py`, `service/indexing.py`, `daemon.py`, `sync/watcher.py` (shared ignore rules), the `tool_style` fixture, tests, the O8 record, spec edits.
- **Not in:** Feature glob expansion / `IMPLEMENTED_IN`, Table/Column, MENTIONS of code files, AFFECTS (all M04b). Leave `# M04b:` comments where they plug in (pipeline step "walker relationships"; the `tracked` set passed to link resolution). Dashboard (M05).
- **Layering:** Cypher only in `graph/` (new `graph/code.py`) and `service/`. `sync/files.py` and `sync/git.py` do filesystem/subprocess work and call `graph.code` functions inside `store.write(job)`. Only `store.py` imports `relate`. No new dependencies (`pathspec` is already there; git through `subprocess`).
- **O8 (already probed by Opus, 2026-11-22):** the `relate` 1.2.0 CLI has `relate extension install|list` and `relate run <name> -d PATH`; `run` help says "the child walks its source and emits rows over the wire; the host alone owns the store". No extension is installed, and installing one fetches from the network. So an extension can only write into a store that the `relate` host opens itself, which our daemon's writer lock prevents. **Decision: keep our walker and git reader.** Record it as **Closed** in the SPEC-00 §8 O8 row with these facts.

## 1. Fixture (M04a.1)

Extend `tests/fixtures/tool_style/` (invented content only; keep the existing kettle files). Our repo must not pick the fixture up as its own: add a root **`.sddignore`** with `tests/fixtures/` (otherwise our graph would get TESTS from fixture test files to our own SPEC-01 checks).

- **Schema spec** `docs/specs/SPEC-02-ingest-schema.md` (the name contains `schema`, so the default `schema_specs` glob matches). H1 `# SPEC-02 — Ingestion schema`; header blockquote with a Feature line:
  `> **Feature:** Ingestion · **Domain:** Library · **Implements:** \`src/ingest/**\` · **Tables:** documents, chunks`
  Sections: `## 1. Overview`; ``## 2. `documents` `` with a `| Column | Type | Rules |` table (`id` uuid PK, `title` text not null, `created_at` timestamptz not null); ``## 3. `chunks` `` (`id` uuid PK, `document_id` uuid `FK → documents` not null, `body` text not null); `## 4. Acceptance checks` with 2–3 checks. Add a `> **DEVIATION:** see [D002](…)` note under §2.
- **Deviation** `docs/deviations/D002-…md` amending `SPEC-02 §2`, `**Date / milestone:** 2026-11-03 · M02 · M02.1`, `**Affects:** \`src/ingest/loader.py\`, \`documents\``; plus its row at the top of `docs/DEVIATIONS.md`. Copy the shape of the existing D001.
- **Milestone** `docs/milestones/M02-ingestion.md`: `Depends on` M01, `Read first` SPEC-02 §2–3, tasks `M02.1` loader (mentions `` `documents` `` and links SPEC-02 §2), `M02.2` chunker (mentions `` `chunks` ``, `(after M02.1)`), `M02.3` tests (`SPEC-02 §4 checks 1–2`).
- **Code tree:** `src/kettle/__init__.py`, `src/kettle/brew.py` (exists), `src/ingest/__init__.py`, `src/ingest/loader.py`, `src/ingest/chunker.py`, `src/util/misc.py` (an orphan file for SPEC-06 check 4), `tests/test_brew.py` with `def test_spec01_ac1_green_default()` and `def test_spec1_ac02_black_default()`, `tests/test_ingest.py` with `test_spec02_ac1_…`, `README.txt` (a non-code text file), a fixture `.gitignore` with `*.log` and `scratch/`. **Ignored files are never committed** (our own repo's git would honour the fixture `.gitignore` too): tests create `scratch/…`, `x.log` and `node_modules/…` in the tmp copy.
- **Scripted history:** `tests/history.py` with `TOOL_STYLE_HISTORY: tuple[Commit, ...]` for `project("tool_style", commits=TOOL_STYLE_HISTORY)`: e.g. `feat: brew model [M01.1]` (changes `src/kettle/brew.py`), `feat: loader [M02.1]` (changes `src/ingest/loader.py`), `chore: tidy (M02)` (changes `src/ingest/chunker.py`, PART_OF M02), `docs: readme` (no ID). `Commit` lives in `tests/conftest.py`; import it from there.
- Adding SPEC-02, M02 and D002 changes counts in existing tool_style tests. Update the assertions to the new correct values; **never weaken an assertion** (no `>=` where `==` was).

## 2. Ignore rules and walker — `sync/files.py` (M04a.2)

```python
BUILTIN_SKIPS = frozenset({".git", ".sdd", "node_modules", ".venv", "venv", "__pycache__",
                           "dist", "build", "bin", "obj", ".next", "coverage", "target"})

def builtin_ignored(rel: str) -> bool        # any path segment in BUILTIN_SKIPS

class IgnoreRules:                           # thread-safe (one lock), lazily loaded, per project root
    def __init__(self, root: Path) -> None
    def ignored(self, rel: str, *, is_dir: bool = False) -> bool
    def invalidate(self) -> None             # drop cached specs; next query re-reads the files
```

- `ignored(rel)`: true if `builtin_ignored(rel)`; else for each ancestor folder `d` of `rel` (root first, then deeper), true if `d` itself is ignored as a folder, or if `d`'s spec matches `rel` relative to `d` (folders matched with a trailing `/`). The spec of a folder = `pathspec.GitIgnoreSpec.from_lines(<d>/.gitignore)`; the root's spec also includes `.sddignore` (gitignore syntax). Files are read lazily and cached per folder. Negation works within one file; **a deeper file cannot un-ignore what a shallower file ignored** (write this into SPEC-04 §4).
- **The blanket "dot names are skipped" rule goes away.** Only the built-in list applies, so `.claude/`, `.github/` and `.gitignore` itself are walked. (`.mypy_cache/` etc. are covered by this repo's `.gitignore`.) Replace `indexer.ignored_dir` / `ignored_path` and every caller with these. `Classifier.classify` keeps a cheap `builtin_ignored` check; the gitignore checks happen in the walkers.
- **Walker:** `walk(root, rules) -> dict[str, tuple[int, int]]`: `{rel: (mtime_ns, size)}` for every non-ignored file, from `os.walk`, pruning folders with `rules.ignored(rel_dir, is_dir=True)`; `followlinks=False`; skip non-regular files. It stops early if passed a `stop` event (the watcher's shutdown check). `discover()` (SDD) and the watcher's `_poll_code` both use it; `_scan_bases` and the native handler use `rules.ignored`. The watcher calls `rules.invalidate()` at the start of each code poll, so `.gitignore` edits are picked up on the next code poll (paths that became ignored disappear from the snapshot and are reported as deleted).
- **FileInfo** (`@dataclass(frozen=True, slots=True)`): `path, name, language, size, lines, content_hash, is_test`. `read_info(root, rel, classifier) -> FileInfo | None` (None if it vanished): read the bytes once; `content_hash = indexer.file_hash(data)` (the same sha256 as SDD files); `lines` only if size < 2 MB and the first 8 KB hold no NUL byte (`data.count(b"\n")`, +1 if non-empty and not ending in `\n`), else `None`; `language` from an extension map (`py python, pyi python, ts/tsx typescript, js/jsx/mjs/cjs javascript, md markdown, json, toml, yaml/yml yaml, html, css, scss, sh/bash shell, ps1 powershell, cs csharp, go, rs rust, java, kt kotlin, sql, txt text`, plus the names `Dockerfile` → `dockerfile`, `Makefile` → `make`), else `None` (property omitted); `is_test` = matches a `tests` glob (build the pathspec the same way as `indexer._spec`; reuse it).
- **Soft cap:** after a full walk, if there are more than `settings.max_files` paths, log one warning (counts only) and keep the first `max_files` sorted by path. An incremental batch that would push the total over the cap applies the same rule to the union and deletes the evicted paths.
- **Ownership (write into SPEC-04 §4):** the walker writes File nodes for **every** walked file, SDD documents included (`path, name, language, size, lines, is_test, last_synced`), but **never `content_hash` on an SDD document**. The indexer sets that hash in its phase 2 as the "fully synced" marker; if the walker set it first, the indexer would skip a changed document. The walker deletes only File nodes of **non-SDD** paths. SDD documents are removed by the indexer (`delete_file`, which already detach-deletes the File node).
- **Folders:** `dir:<path>` (`path`, `name`, `last_synced`) for every folder on the path of a kept file. **No root Folder node**: top-level files and folders have no parent (SPEC-02 §3 note). `CONTAINS {src: 'walker'}` from parent Folder to child Folder/File. A Folder left with no children after a sync is deleted (repeat up the tree).
- **Write only differences.** `CodeCache = dict[str, FileInfo]` held by the runtime. A full sync reads the stored code layer once (`graph.code.read_code_state`: File props by path, Folder paths, existing CONTAINS pairs) and diffs it against the walk. A batch re-reads only its paths and diffs them against the cache. Unchanged files are not written. Re-syncing an unchanged repo writes nothing (SPEC-04 §7 check 2 must still hold with code files present).

`graph/code.py` (plain data in, Cypher out, like `upsert.py`; UNWIND in chunks of ~500 rows): `read_code_state(store|tx)`, `upsert_folders(tx, rows, now)`, `upsert_files(tx, rows, now)` (`SET f += row.props`; never sends `content_hash` for SDD paths), `delete_files(tx, paths)` (DETACH DELETE), `add_contains(tx, pairs)`, `prune_empty_folders(tx) -> list[str]`, `replace_tests(tx, file_id, check_ids)`, the git functions of §5, `set_last_git_sha(tx, sha)`, `read_git_state(store|tx)`. Validate labels and relationship types against `schema` as `upsert.py` does.

## 3. Indexer scoping (M04a.6)

`upsert.read_state` keeps returning every hashed File and every catalog row. **`indexer` filters it** through its `Classifier` before use (both in `sync` and `sync_tx`):
- `state.files` → only paths that classify as SDD documents (so code files are never "removed" by the Markdown sync);
- `state.catalog_rows` with `label == "File"` → only SDD paths (otherwise `catalog_fingerprint` differs on every sync once code files exist, and phase 2 re-links everything each time).
Add a regression test: with code File nodes present, a second full sync deletes no File node and re-links 0 files.

## 4. TESTS (M04a.3)

- After the indexer step, scan test files (`is_test`) whose content changed in this sync (all test files on a full sync, **and all of them whenever the batch created or deleted an AcceptanceCheck**, so a check added later still gets its tests). Regex `spec(\d+)_ac(\d+)` with `re.IGNORECASE`; target `SPEC-{int(a):02d}#ac{int(b)}`, kept only if that AcceptanceCheck exists. Text = bytes decoded as UTF-8 with `errors="replace"`, only for files under 2 MB.
- `TESTS {src: 'walker'}`, File → AcceptanceCheck, one per distinct pair; rewrite a file's TESTS only when the desired set differs from the stored one. A test file that is deleted loses them through DETACH DELETE.

## 5. Git — `sync/git.py` (M04a.4)

**Reader (pure subprocess, no store):** every call is `git -c core.quotepath=off --no-optional-locks -C <root> …` with `GIT_TERMINAL_PROMPT=0`, a 30 s timeout and `check=True`. No git binary, not a repository, or no commits yet (`rev-parse` fails) → git sync is skipped and `report.git = None` (log once at info; never an error).
- `head() -> str | None`: `git rev-parse HEAD`.
- `is_ancestor(a, b) -> bool`: `git merge-base --is-ancestor`, where exit 1 means false (do not raise).
- `log(range_or_head, max_count) -> list[CommitIn]`: `git log --reverse -n <max> --name-status --format=%x1e%H%x1f%P%x1f%an%x1f%aI%x1f%s <rev>`. Split records on `\x1e`. Name-status lines `X\tpath` or `R100\told\tnew` (and `C…` the same way). Change letters: `A, M, D` as is, `R*` → `R` (path = new; `paths` gets both old and new), `C*` → `A`, `T` → `M`. Merge commits list no files (git's default; keep it). `author` = **name only, no email** (the graph is public in M06b). `at` = `%aI` converted to UTC `…Z`. `message` = the subject.
- `CommitIn(sha, parents, author, at, message, changes: list[tuple[str, str]], paths: list[str])`.
- Task IDs: every `\[(M\d+[a-z]?\.\d+)\]` in the subject, normalised with `ids.normalise`. When there are none: milestones from `\((M\d+[a-z]?)\)` or `\bM\d+[a-z]?\b`, normalised.

**Sync** (`sync_git(store, settings, *, code_step) -> GitReport | None`), with `Meta.last_git_sha` = `last`:
1. `head` is None → skip. `head == last` → nothing to do.
2. `last` is None → first sync: `log(HEAD, git_max_commits)`.
   `last` is an ancestor of HEAD → `log(f"{last}..HEAD", git_max_commits)`.
   Otherwise (**history rewritten**): `reachable = git rev-list -n <max> HEAD`; delete every Commit node not in `reachable`, then every relationship whose `src` is `git:<that sha>` (`TOUCHES` is Task→File, so a detach of the Commit does not remove it). Run this in its **own job**, before the job that adds commits: the engine panics when one transaction deletes a relationship it created. Then `log(HEAD, max)`, minus the commits already in the graph.
3. Before linking, pass the new commits' existing, non-ignored paths through the **code step** (§6) so that `CHANGED`/`TOUCHES` find File nodes for files created in the same commit. That is what makes "TOUCHES within 3 s of the commit" hold, since the code poll alone waits ≥ 10 s.
4. Write in jobs of ~200 commits, oldest first: the Commit node (`id commit:<sha>`, `sha, short (7), message, author, at, paths, last_synced`); `PARENT` to parents already in the graph; `CHANGED {change}` to File nodes that exist; `COMPLETES` to existing Tasks; `PART_OF` to existing Milestones (only when there is no task ID); `TOUCHES` from each completed task to the commit's changed files that exist. Every relationship gets `src = "git:<sha>"`. A Task or Milestone missing at sync time gets no link (no `unresolved`); note this in SPEC-04 §6. The last job sets `Meta.last_git_sha = head`. Commits create **no Events** and never change task status.
5. `GitReport(added, removed, head)`; the new and removed `commit:<sha>` IDs join `changed_ids`.

**HEAD poller:** `class HeadPoller(root, on_change, interval=3.0)` runs a daemon thread that polls `head()` every `interval` (SPEC-04 §6: 3 s) and calls `on_change(sha)` when the value differs from the last one seen. Errors are logged by type only and the loop keeps running. `start()` / `stop()` join like the watcher. The daemon starts it next to the watcher and stops it in `cleanup()` before `runtime.close()`.

## 6. One sync order — `sync/pipeline.py`

```python
@dataclass
class SyncState:                 # held by Runtime; built fresh for a one-shot `sdd sync`
    parse: indexer.ParseCache
    code: files.CodeCache
    rules: files.IgnoreRules

def run(store, settings, state, *, full: bool, paths: Iterable[str] = (),
        sdd_files: Mapping[str, str] | None = None, git: bool = False) -> indexer.SyncReport
```
Order (SPEC-04 §2 steps 4–6, then §6):
1. `state.rules.invalidate()`. **Code phase 1:** on a full sync, walk everything; otherwise handle `paths`. A path that exists on disk and is not ignored → `read_info`, then upsert if it differs from the cache. A path that is gone or ignored and non-SDD → delete. Add folders and `CONTAINS` for new entries.
2. **Indexer** (`indexer.sync(..., files=sdd_files, cache=state.parse)`): always on a full sync; on a batch only if a path is an SDD document or was tracked (today's `Runtime.on_batch` test). `# M04b: pass the code paths into link resolution here.`
3. **Walker relationships:** TESTS (§4), prune empty folders. `# M04b: feature glob re-expansion here.`
4. **Git** when `full` or `git=True`. Its step 3 calls back into the code step for the commits' paths.
5. One `checkpoint()` if anything was written, then return one `SyncReport` that gains `code: CodeReport | None` (`added, updated, removed, folders, tests_links, capped`) and `git: GitReport | None`. `changed_ids` merges every step (`file:…`, `dir:…`, `commit:…`).

Callers: `Runtime.sync(full=True)` (startup and `POST /api/sync`) calls `run(full=True)`. `Runtime.on_batch` calls `run(full=False, paths=batch.paths, sdd_files=batch.sdd_files)` for **every** batch, not just SDD ones. Add `Runtime.on_head(sha)` → `run(full=False, git=True)`. All of them run under `sync_lock`. `service/indexing.sync` (`sdd sync`) builds a fresh `SyncState` and calls `run(full=True)`. `daemon.prepare` drops its `# M04a: git sync` comment. `report_dict` gains `"code"` and `"git"` objects (`null` when skipped); add them to the `sdd sync` row in SPEC-08 §2 and wherever SPEC-07 describes the `POST /api/sync` result.

## 7. Tests (M04a.5): names per SPEC-10 §1, in `tests/spec04/` and `tests/spec02/`

- `test_spec04_ac08_gitignored_and_node_modules_produce_no_file_nodes`: tool_style copy plus `scratch/a.txt`, `x.log`, `node_modules/p/index.js`, `.venv/lib/x.py` → none of them has a File node; `src/ingest/loader.py` does, with `language = "python"`, a `lines` count and a `content_hash`; `tests/test_brew.py` has `is_test = true`.
- `test_spec04_ac09_commit_completes_touches_and_reset_removes`: `project("tool_style", commits=TOOL_STYLE_HISTORY + (Commit("feat: walker [M01.2]", {...}),))` → COMPLETES to M01.2, TOUCHES to the changed files, CHANGED with `change`; then `git reset --hard HEAD~1` plus a git sync → that Commit node and its `git:<sha>` TOUCHES are gone.
- `test_m04a_tool_touches_survive_reset`: `complete_task(files_touched=[…])` for the same task and file, then the reset → the `src = 'tool'` TOUCHES remains.
- `test_spec02_ac05_no_file_node_holds_contents`: after a full sync, every File property is in the SPEC-02 §3 list plus `id`, `last_synced` (and `source_path` is absent); no value is longer than 200 characters, except `content_hash`, which is exactly 64 hex characters.
- Also: TESTS integer rule (`spec1_ac02` → `SPEC-01#ac2`; `SPEC-02#ac1`; an unknown check creates nothing); the M04a.6 regression (§3); a second full sync of an unchanged repo with code files writes 0 changes (a code + SDD version of check 2); PART_OF on `(M02)` with no task ID; first-sync limit (`git_max_commits=2` keeps the 2 newest); a non-git project syncs with `git = None`; nested `.gitignore` and `.sddignore`; folder pruning when the last file goes; the soft cap (`max_files=3`); a watcher batch with only code paths updates a File node; `HeadPoller` calls back on a new commit (short interval).
- Existing tests must stay green. Watcher tests that relied on dot folders being skipped need a look: `.sdd/` and `.git/` are still built-in skips.
- Full gates: `ruff check`, `ruff format --check`, `mypy src/sdd`, `lint-imports`, `pytest -q`.

## 8. Do not commit

Leave the work uncommitted; Opus reviews it, commits as `feat: code and git layer [M04a.1] … [M04a.6]`, and runs the acceptance-2 walkthrough on that commit with the daemon running.

## 9. Spec and doc changes in the same change

- **SPEC-00 §8:** close O8 (the facts in §0).
- **SPEC-04 §4:** the ignore semantics (built-in list only, with no blanket dot skip; nested `.gitignore` per folder, where a deeper file can't un-ignore; `.sddignore` at the root), the ownership rule (no walker `content_hash` on SDD documents; the walker deletes only non-SDD File nodes), the `lines` text rule, no root Folder, empty-folder pruning, writes only on differences, the TESTS rescan on AcceptanceCheck changes, and the cap applied to batches.
- **SPEC-04 §6:** the exact `git log` format, author = name only, the commits' paths go through the code step first, rewrite deletes run in their own transaction, a missing task/milestone means no link, no repo = skipped.
- **SPEC-04 §1:** the watcher's code poll re-reads ignore files on each poll.
- **SPEC-02 §3:** there is no root Folder; the File properties apply to SDD documents too, and only the indexer sets their `content_hash`.
- **SPEC-08 §2 / SPEC-07:** the new `code` / `git` fields of the sync result.
- `tests/fixtures/README.md`: describe the extended tool_style fixture and `tests/history.py`.
