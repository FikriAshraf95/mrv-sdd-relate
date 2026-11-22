# SPEC-11 — Deployment and demo

> **Status:** v1 (2026-11-21) · **Owner of:** the Dockerfile and Compose files, the development container, home hosting, sprint replay, the sample project, the static demo, the submission checklist

## 1. Development container

All building, testing and running happens in Docker. The Windows host's C: drive is nearly full; Docker's data lives on D:, so images, volumes and caches stay off C:.

- `Dockerfile`, stage **`dev`**: `python:3.13-slim` (glibc; `relate-db` has no musllinux wheel) + `git`, `curl`, `ca-certificates`, `openssh-client`, `uv` (copied from `ghcr.io/astral-sh/uv`), the Relate CLI (official install script into `HOME=/opt/relate`, linked onto `PATH`; amd64 + arm64; how and why: O9 in [SPEC-00 §8](SPEC-00-overview.md#8-schedule-and-open-items)), `DO_NOT_TRACK=1` (turns off the CLI's default-on telemetry), and `git config --system --add safe.directory '*'` (system level, so it also applies to other users).
- `UV_PROJECT_ENVIRONMENT=/opt/venv`, so the virtualenv lives in a **named volume**, not on the bind mount (fast, and no Windows/Linux venv clash). `UV_CACHE_DIR=/cache/uv` in another named volume. `UV_LINK_MODE=copy`.
- `SDD_WATCH=poll` (inotify misses host edits through the bind mount).
- Usage:

```bash
docker compose -f docker-compose.dev.yml up -d dev                 # long-running dev container
docker compose -f docker-compose.dev.yml exec dev uv sync          # deps into /opt/venv
docker compose -f docker-compose.dev.yml exec dev uv run pytest -q
docker compose -f docker-compose.dev.yml exec dev uv run sdd daemon --host 0.0.0.0   # :8770 on host loopback
```

## 2. Compose

| File | For | Services |
|---|---|---|
| `docker-compose.dev.yml` | Development | `dev` (bind mount `.:/workspace`, volumes `venv`, `uvcache`, port `127.0.0.1:8770:8770`, `command: sleep infinity`) |
| `docker-compose.yml` | **Judges**: `docker compose up` | `sample`: the runtime image running `sdd demo serve` (prepare, then the daemon; [SPEC-08 §2](SPEC-08-cli-and-exports.md#2-commands)) on a copy of the sample project in a volume, port `127.0.0.1:8770:8770`. Dashboard at `http://localhost:8770` |
| `deploy/docker-compose.yml` | Home server ([§7](#7-home-hosting)) | `replay` (writer, [§4](#4-sprint-replay)), `public` (`sdd public`, store volume mounted read-only), `cloudflared` (profile `tunnel`) |

Inside containers the daemon binds `0.0.0.0` with `SDD_ALLOW_REMOTE=1`; the root Compose files publish every port on `127.0.0.1` only ([SPEC-09 §2](SPEC-09-security.md#2-local-daemon)). All long-running services: `restart: unless-stopped`, a healthcheck, and the limits in [SPEC-09 §5](SPEC-09-security.md#5-hosted-demo-infrastructure). Services with HTTP (`sample`, `public`) check `/api/health`. `replay` has no HTTP server: it touches `/data/run/.sdd/replay.heartbeat` every tick, and its healthcheck passes when that file exists and is younger than 30 s.

## 3. Runtime image

Stage **`build`**: `uv sync --frozen --no-dev --no-editable` into `/opt/venv` (non-editable, so the venv does not point back at the build stage's source tree). Stage **`runtime`**: `python:3.13-slim` + `git` (for git sync) + `/opt/venv` + `src/` + `samples/`; non-root user `sdd` (uid 10001); `ENTRYPOINT ["sdd"]`; no image-level `HEALTHCHECK` (it depends on the command, so each Compose service sets its own, [§2](#2-compose)). Target size < 250 MB. Builds for `linux/amd64` and `linux/arm64`.

## 4. Sprint replay

`sdd demo replay --sample samples/<name> --data /data` makes the hosted demo move:

1. **Prepare:** copy the sample's working tree and history into `/data/run` (a fresh git repo from the sample's bundle, [§5](#5-sample-project)) and apply its `replay.toml` start state (which milestones start unticked).
2. **Run** in-process (the replay process owns `/data/run/.sdd/graph`): one orchestrator and three workers named `opus-orch`, `sonnet-1…3`. Every tick (`SDD_REPLAY_TICK`, default 4 s) an idle worker calls `next_tasks` → `claim_task`; a busy worker finishes after 2–5 ticks with `complete_task` (notes and files from `replay.toml`, or generated from the task's governed sections). Deviations scripted in `replay.toml` are logged on their tasks with `log_deviation`. When a milestone's tasks are done, the orchestrator calls `complete_milestone`.
3. **Checkpoint** after every write, so `public` sees it on its next reopen (≤ 2 s).
4. **Loop:** when the scripted milestones are done or after `SDD_REPLAY_MAX_MIN` (default 20) minutes, pause 30 s, reset to step 1, and continue. Deterministic with `--seed`.

## 5. Sample project

`samples/<name>/` is the project judges explore. It is **invented**: office-suite-v2 cannot be made public (open item O1, closed "no"; [DEC-004](../decisions/DEC-004-sample-fallback.md)), so no text, file name, commit message or structure specific to it is copied. Only its *conventions* are used, which are generic.

- **Format:** the office-suite conventions (`**Spec ID:**` headers, `### <table>` schema tables with `→ <table> [restrict]`, letter-suffixed milestones, `**Status: DONE (…)**` paragraphs, plan files, nested `> > **DEVIATION:**` notes), plus this tool's conventions (task IDs, `(after …)`, Feature lines). It grows out of the `suite_style` fixture ([SPEC-10 §3](SPEC-10-testing-and-benchmark.md#3-fixtures)).
- **Size:** about 6 specs (one schema spec with 6–8 tables), 8 milestones (some done, some letter-suffixed, one with a plan file), about 6 deviations, and a code tree of small placeholder files grouped by feature, so Feature globs, `explain` and `find_code` have something to show.
- **History:** `scripts/make_sample.py` scripts a linear git history (as `samples/<name>.bundle`) that builds the milestones in order, with commits naming their tasks (`[M03.2]`), so `COMPLETES`, `TOUCHES` and `explain` have real data.
- **Story by design:** one table is touched by several specs, milestones and deviations, so `impact` on it is the centrepiece shot (SPEC-00 §7 item 5). Some milestones are left unticked in `replay.toml` for the live replay ([§4](#4-sprint-replay)).
- **Store:** `make_sample.py` finally runs `sdd sync` and `sdd snapshot` on the sample. Its `.sdd/graph/` is a build output that no daemon ever runs on (judges' Compose and the replay work on a copy in a volume), so it is committed as is, with the snapshot copies ([SPEC-08 §3](SPEC-08-cli-and-exports.md#3-exports-and-snapshots), [DEC-001](../decisions/DEC-001-committed-store.md)).

This repo's own `docs/` and store are a second, smaller example (dogfooding).

## 6. Static demo (GitHub Pages)

A GitHub Actions workflow builds `site/`: the dashboard's static files + the sample graph exported with `sdd export --cypher` and `--json`, + precomputed API answers for the presets and the demo targets. The dashboard's data adapter loads the graph into **Relate's WASM build** in memory and runs the same named Cypher queries the daemon uses (all of `service/impact.py`'s Cypher lives in `graph/queries/*.cypher`, so both share it). If the WASM build is unavailable or too slow (open item O2), the adapter serves the precomputed answers, and the Query tab offers presets only. No live updates; the Board shows the final state with a "Replay" button that animates the recorded events.

## 7. Home hosting

The same pattern as office-suite-v2's `deploy/` (copy the shape, not the services): the home server runs Docker, and a **remotely managed Cloudflare tunnel** publishes one hostname. Nothing is opened on the router.

### 7.1 Files
- `deploy/docker-compose.yml`, with `name: relate-sdd` so it never clashes with other stacks on the server (office-suite runs as `office-suite`).
- `deploy/.env.example`, committed, placeholders only; copied to `deploy/.env` (gitignored by M00a.1):

```bash
# Copy to deploy/.env (git-ignored) and replace every CHANGE_ME. Placeholders only: never commit real values.

# Images (built on the server from this repo: `docker compose build`)
IMAGE_PREFIX=relate-sdd
IMAGE_TAG=local
# The compose network, and the only network `public` trusts for CF-Connecting-IP / X-Forwarded-For.
# Must differ from other stacks on the host (office-suite uses 172.30.0.0/24).
COMPOSE_SUBNET=172.31.0.0/24

# The public HTTPS hostname (shown in the dashboard footer and used for absolute links)
PUBLIC_BASE_URL=https://CHANGE_ME.example.com
# Optional host port for `public`, for checking it on the server or for an existing tunnel that
# reaches services through the host. Loopback by default; never 0.0.0.0 unless the LAN may see it.
PUBLIC_BIND=127.0.0.1
PUBLIC_PORT=8780

# Demo behaviour
SAMPLE=CHANGE_ME                  # folder name under samples/
SDD_PUBLIC_QUERY=guarded          # guarded | presets
SDD_REPLAY_TICK=4
SDD_REPLAY_MAX_MIN=20
SDD_REPLAY_SEED=42
TZ=UTC

# Cloudflare tunnel (remotely managed): the token from Zero Trust → Networks → Tunnels.
# Start with `docker compose --profile tunnel up -d`.
TUNNEL_TOKEN=
CLOUDFLARED_VERSION=2026.10.3
```

No other secrets: the hosted demo has no database, no accounts and no write path.

### 7.2 Services
| Service | Image | Networks | Notes |
|---|---|---|---|
| `replay` | `${IMAGE_PREFIX}/sdd:${IMAGE_TAG}` | `default` | `sdd demo replay`; volume `demo-data` read-write; the only writer |
| `public` | same image | `default` | `sdd public --store /data/run/.sdd/graph`; `demo-data` mounted **read-only**; `ports: ['${PUBLIC_BIND:-127.0.0.1}:${PUBLIC_PORT:-8780}:8780']`; healthcheck on `/api/health`; `depends_on: replay` (healthy) |
| `cloudflared` | `cloudflare/cloudflared:${CLOUDFLARED_VERSION}` | `default` | `profiles: ['tunnel']`, `command: ['tunnel', '--no-autoupdate', 'run']`, `TUNNEL_TOKEN` from `.env`; no ports |

`default` has the fixed subnet `${COMPOSE_SUBNET}`. `public` takes the client IP for rate limiting from `CF-Connecting-IP` **only** when the request comes from that subnet, otherwise from the socket. So nobody on the LAN can pick the IP the rate limiter sees ([SPEC-09 §4](SPEC-09-security.md#4-public-mode)). Hardening and limits: [SPEC-09 §5](SPEC-09-security.md#5-hosted-demo-infrastructure).

### 7.3 Run book (`deploy/README.md`)
1. On the server: `git clone` this repo, `cd deploy`, `cp .env.example .env`, fill it in.
2. `docker compose build` then `docker compose up -d`; check `curl http://127.0.0.1:8780/api/health` shows `mode: public`.
3. Cloudflare Zero Trust → Tunnels → create a tunnel (Docker connector), copy its token into `TUNNEL_TOKEN`, then `docker compose --profile tunnel up -d`.
4. Tunnel → Public hostname: `CHANGE_ME.example.com` → service `http://public:8780`.
   **If the server already runs a shared cloudflared** for other apps, skip the `tunnel` profile and point that tunnel at `http://<server-host>:8780` instead (set `PUBLIC_BIND` to an address it can reach), or attach its container to this stack's network.
5. Cloudflare rules: rate-limit `POST /api/query` (e.g. 30/min per IP), cache the dashboard's assets by extension (`.js`, `.css`, `.svg`: the dashboard is served at `/`, not under a `/static/` prefix; never `/api/*`, and not `/` itself so a deploy shows at once), and turn on Bot Fight Mode. SSE (`/api/events`) passes through tunnels; the dashboard falls back to polling if a proxy buffers it.
6. Update: `git pull && docker compose build && docker compose up -d`. The replay resets itself, so no data migration is needed.

The README links **"Live demo (home-hosted) · Static demo (GitHub Pages, always up)"**. Judging may run weeks past the deadline, which is why the static demo exists.

## 8. Submission checklist (M99)

- Public GitHub repo with topics `relate` and `relate-neo4j-hackathon`.
- README (Devpost template): what it is, setup with Docker and with `pip`/`uvx`, usage, **how Relate is used (directory store owned by one daemon; `read_only` snapshots for the public side; `.rl` and JSON copies committed) and why**, what connects to what (Mermaid schema), the benchmark table, comparison with Spec Kit and Beads, demo links, a GIF of the Board.
- Committed persistent stores: the sample's built store with its snapshot copies, and this repo's `sdd snapshot` output (directory + `.rl`). Never this repo's live `.sdd/graph/`.
- 1–2 minute demo video; Devpost description with the use case and what connects to what.

## 9. Acceptance checks

1. `docker compose -f docker-compose.dev.yml exec dev uv run pytest -q` passes, and nothing is written outside the repo, the named volumes and Docker's data folder.
2. On a clean clone, `docker compose up` serves the sample dashboard at `http://localhost:8770` with a populated graph.
3. The `public` service answers `/api/health` with `mode: public`, follows the replay within 2 s of each write, returns 403 for writes and 404 for `/mcp`.
4. The replay loops: after the reset, the Board returns to its start state and starts moving again.
5. The static site loads on GitHub Pages and the Impact view works for the demo target with no backend.
6. The runtime image is under 250 MB and runs as uid 10001.
