# M00a — Docker dev environment and package skeleton

> **Depends on:** — · **Blocks:** [M00b](M00b-relate-access-layer.md)
> **Read first:** [SPEC-00 §6](../specs/SPEC-00-overview.md#6-global-conventions) · [SPEC-01 §2–3, §6](../specs/SPEC-01-architecture.md#2-repo-layout) · [SPEC-02 §1](../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties) · [SPEC-08 §1–2](../specs/SPEC-08-cli-and-exports.md#1-rules) · [SPEC-10 §1–2, §6](../specs/SPEC-10-testing-and-benchmark.md#1-conventions) · [SPEC-11 §1–3](../specs/SPEC-11-deployment-and-demo.md#1-development-container)
> **Model:** Opus. The Docker and package contracts every later milestone builds on.
> **Split from:** M00 (2026-11-21)

## Goal
Everything runs in Docker on D:, nothing on the Windows host. A dev container with uv and the Relate CLI, the Python package skeleton with config, errors, IDs and the CLI entry point, the test host and CI. No store layer yet (M00b), no parsing.

## Tasks
### Repo and Docker
- [ ] **M00a.1** `git init`; `.gitignore` (`.venv/`, `__pycache__/`, `.sdd/daemon.json`, `/.sdd/graph/` (this repo's live store, root only: the sample's built store under `samples/` is committed; [DEC-001](../decisions/DEC-001-committed-store.md)), `**/.sdd/graph/.cypherlite.*`, `deploy/.env`, `bench/results/*.tmp`); `.gitattributes` (`* text=auto eol=lf`); `.editorconfig`.
- [ ] **M00a.2** `Dockerfile` with stages `dev`, `build`, `runtime` ([SPEC-11 §1, §3](../specs/SPEC-11-deployment-and-demo.md#1-development-container)); the runtime stage only needs to run `sdd --version` for now.
- [ ] **M00a.3** `docker-compose.dev.yml`: `dev` service, bind mount, named volumes `venv` and `uvcache`, `127.0.0.1:8770`, `SDD_WATCH=poll`, plus **read-only** mounts of the reference docs: `D:/Works/ai/office-rag/docs` → `/refs/office-rag/docs` and `D:/Works/ai/office-suite-v2/docs` → `/refs/office-suite/docs` (and their CLAUDE.md files). (after M00a.2)
- [ ] **M00a.4** Resolve open item O9: install the Relate CLI in the `dev` stage (first check whether the `relate-db` wheel already ships it) and record the method in SPEC-00 §8. (after M00a.2)
### Package
- [ ] **M00a.5** `pyproject.toml` (uv, hatchling, `src/` layout, `requires-python = "==3.13.*"`, runtime and dev deps from [SPEC-01 §6](../specs/SPEC-01-architecture.md#6-dependencies), script `sdd = "sdd.cli:app"`), `uv.lock`, ruff, mypy (strict) and the import-linter contracts from the table in [SPEC-01 §3](../specs/SPEC-01-architecture.md#3-module-boundaries).
- [ ] **M00a.6** `config.py`, `errors.py`, `ids.py` with `normalise()` for every form and padding rule in [SPEC-02 §1](../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties). (after M00a.5)
- [ ] **M00a.7** `cli.py`: `sdd --version` (prints the `sdd` and `relate-db` versions) and the global options `--project`, `--store`, `--json` ([SPEC-08 §1–2](../specs/SPEC-08-cli-and-exports.md#1-rules)). (after M00a.6)
### Tests and CI
- [ ] **M00a.8** `tests/conftest.py`: `project` fixture (copies a fixture repo into `tmp_path`, optional scripted `git init`), `pytest-socket` guard ([SPEC-10 §2](../specs/SPEC-10-testing-and-benchmark.md#2-test-host)).
- [ ] **M00a.9** [SPEC-02 §8](../specs/SPEC-02-graph-schema.md#8-acceptance-checks) check 1; [SPEC-01 §7](../specs/SPEC-01-architecture.md#7-acceptance-checks) check 6; [SPEC-10 §7](../specs/SPEC-10-testing-and-benchmark.md#7-acceptance-checks) check 1; invariant 1.
- [ ] **M00a.10** GitHub Actions: build the `dev` image, run the gates inside it ([SPEC-10 §6](../specs/SPEC-10-testing-and-benchmark.md#6-gates)).

## Acceptance criteria
1. The tests above are green, along with the full gates, **inside the dev container**.
2. **Walkthrough:** `docker compose -f docker-compose.dev.yml up -d dev` → `exec dev uv sync` → `exec dev uv run pytest -q` → `exec dev uv run sdd --version` prints both versions → `exec dev relate --version` works → `ls /refs/office-suite/docs/specs` lists the reference specs and writing there fails (read-only). No Python, venv or cache was created on C:.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
