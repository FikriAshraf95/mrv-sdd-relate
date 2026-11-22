# Contributing

> **For:** developers who want to build, test or extend SDD Graph itself. This repo is spec-driven and built with its own tool, so contributing means following the workflow the tool supports.

## Rules that must never break

- **Only `src/sdd/graph/store.py` imports `relate`.** All graph writes go through its write queue; all Markdown writes go through `src/sdd/sync/writeback.py`. An import-linter contract enforces the layering.
- **One process owns a store.** Never open a writable connection outside the daemon (or `sdd sync` when no daemon runs).
- **Markdown is the source of truth.** The graph holds nothing a rebuild can't reproduce, except the graph-only state listed in [SPEC-02 §2](../specs/SPEC-02-graph-schema.md#graph-only-state-canonical-list).
- **The public process** opens the store read-only, never mounts `/mcp`, and serves no write route.
- **Arbitrary Cypher only through the query guard**, always rolled back.
- **Tests never touch the network**; they use the fixture repos in `tests/fixtures/`.
- **Never commit the live store** (`/.sdd/graph/`) or a secret (`SDD_TOKEN`, `TUNNEL_TOKEN`, `ANTHROPIC_API_KEY`). Secrets live only in the environment or `deploy/.env`.

## Dev environment (Docker only)

Everything builds, tests and runs in the dev container. Nothing needs installing on the host except Docker.

```bash
docker compose -f docker-compose.dev.yml up -d dev          # long-running container (uv, git, the relate CLI)
docker compose -f docker-compose.dev.yml exec dev uv sync   # dependencies into a named volume (/opt/venv)
```

The repo is bind-mounted at `/workspace`; the virtualenv and uv cache live in named volumes, so nothing Linux-specific lands in your checkout. The container polls for file changes (`SDD_WATCH=poll`), because inotify misses host edits through a bind mount. In Git Bash, prefix commands that pass container paths with `MSYS_NO_PATHCONV=1`.

> The dev compose file also mounts two read-only reference projects by default (`SDD_REF_RAG`, `SDD_REF_SUITE`) for `sdd doctor` format checks. Point those variables at your own folders, or remove the mounts if you don't have them.

## Gates

All of these must pass before a change is done (they also run in CI):

```bash
docker compose -f docker-compose.dev.yml exec dev uv run pytest -q
docker compose -f docker-compose.dev.yml exec dev sh -c \
  "uv run ruff check . && uv run ruff format --check . && uv run mypy src/sdd && uv run lint-imports"
```

Run one test:

```bash
docker compose -f docker-compose.dev.yml exec dev uv run pytest tests/spec05/test_claims.py::test_spec05_ac03_double_claim_one_winner
```

## Tests

- **Every numbered acceptance check in a spec becomes a test named after it:** `test_spec05_ac03_double_claim_one_winner`, in `tests/spec05/`. That naming also feeds the tool: the walker links the test file to `SPEC-05#ac3`.
- Assert on error `code`, never on message text.
- **Never mock Relate or the write queue.** Tests use a real directory store in `tmp_path` and Starlette's in-process `TestClient`. Only time (an injected clock) and the benchmark's HTTP client are mocked.
- `pytest-socket` blocks the network.
- The **invariant suite** (`tests/invariants/`) checks layering, rebuild equivalence, graph-only state, exact write-back diffs, the public route list, doc-to-code drift (the MCP tools, endpoints and commands in the specs must match what the code registers) and the query guard corpus.

## The workflow (dogfooding)

Specs in `docs/specs/` are the source of truth, and milestones in `docs/milestones/` are worked in number order. Read [CLAUDE.md](../../CLAUDE.md) and [SPEC-00 §6](../specs/SPEC-00-overview.md#6-global-conventions) before non-trivial work.

1. Start the daemon on this repo in the dev container: `docker compose -f docker-compose.dev.yml exec -d dev uv run sdd daemon --host 0.0.0.0`. `.mcp.json` already points Claude Code at it.
2. Work tasks with the protocol in [agents.md](agents.md): `claim_task` → `get_context` → build and test → `log_deviation` → `complete_task`.
3. Commit with the task ID: `feat: walker [M04.1]`.

### Changing contracts

- **A new label or relationship type** is a [SPEC-02](../specs/SPEC-02-graph-schema.md) change in the same change as the code.
- **A new MCP tool, HTTP endpoint or CLI command** goes in [SPEC-05 §2](../specs/SPEC-05-agent-tools.md#2-tool-index), [SPEC-07 §2](../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index) or [SPEC-08 §2](../specs/SPEC-08-cli-and-exports.md#2-commands) respectively. The drift invariant fails otherwise. Update this manual's [reference pages](README.md#reference) too.
- **A new error code** goes in [SPEC-05 §8](../specs/SPEC-05-agent-tools.md#8-error-codes), with an HTTP status in SPEC-07 §1 and a CLI exit code in `cli.py`.
- **A new named query** goes in `src/sdd/graph/queries/*.cypher`; `service/` holds no Cypher of its own, and the static demo shares these files.
- **Any departure from a spec** is logged as a deviation (`docs/deviations/D<nnn>-….md` + index row + spec note) in the same change. An unlogged deviation is a bug.

## Where things live

| Path | Contents |
|---|---|
| `src/sdd/config.py` | settings from env and `.sdd/config.toml` (the only reader of `os.environ`) |
| `src/sdd/parse/` | pure parsers: text in, parsed objects and warnings out |
| `src/sdd/graph/` | `store.py` (the only Relate import, write queue), `schema.py`, `upsert.py`, `queries/*.cypher` |
| `src/sdd/sync/` | watcher, indexer, code walker, git reader, `writeback.py` |
| `src/sdd/service/` | coordination, context packets, changes, impact/explain/find, query guard, exports, bench |
| `src/sdd/mcp/server.py` | MCP tools → service |
| `src/sdd/web/` | Starlette routes, SSE, public mode, the static dashboard (no build step) |
| `src/sdd/cli.py` | the `sdd` Typer app |
| `src/sdd/daemon.py`, `public.py` | process wiring |
| `src/sdd/demo/` | sample preparation and the sprint replay |
| `tests/` | pytest, `fixtures/` (small repos in three formats, invented content) |
| `samples/courtside/` | the invented sample, rebuilt by `scripts/make_sample.py` |
| `deploy/` | the home-hosted public demo stack |

## Rebuilding the sample

The sample's files, git bundle and committed store are generated together:

```bash
docker compose -f docker-compose.dev.yml exec dev uv run python scripts/make_sample.py
```

It replays the scripted history, checks the tip tree against `samples/courtside/` byte for byte, syncs, snapshots, and fails unless `sdd doctor` shows zero warnings and `impact bookings` fills every group.
