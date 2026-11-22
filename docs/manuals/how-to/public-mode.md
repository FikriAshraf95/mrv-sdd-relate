# Run the read-only public mode

> **For:** anyone who wants to show a graph to others (a team dashboard, a demo, a review) without letting them change anything.

`sdd public` is a **separate process** from the daemon. It opens a store **read-only**, serves the dashboard and the read endpoints, and nothing else.

## Run it

On a committed snapshot:

```bash
sdd public --store .sdd/snapshots/graph --project .
```

Following a live daemon's store (the public process re-opens it when it changes):

```bash
sdd public --store .sdd/graph          # --project defaults to two folders up when the path ends in .sdd/graph
```

Open `http://localhost:8780`. The footer shows the project name, and `/api/health` answers `"mode": "public"`.

Flags: `--host` (default `127.0.0.1`), `--port` (default `8780`). Binding beyond loopback follows the daemon's rule: `SDD_ALLOW_REMOTE=1` is required.

## What it does and doesn't serve

| | Public mode |
|---|---|
| Dashboard (Board, Graph, Impact, Explain, Query) | ✓ |
| Read endpoints (`/api/status`, `/api/graph`, `/api/impact`, …, `/api/events`) | ✓ |
| `POST /api/query` | ✓ through the query guard, or presets only (below) |
| Write endpoints (claim, release, complete, deviations, milestone complete, sync) | **403 `read_only`** |
| `/mcp` | **404**: not mounted at all |
| Any other non-GET request to an unknown path | 404 |
| `agent` parameters | ignored (some read paths would record agent state) |

## How it follows a live store

Python can't follow Relate's write-ahead log, so the public process checks the store's `manifest.json` every 2 seconds and re-opens the store when it changes. It then compares the new snapshot with the old one and publishes live events (`task`, `milestone`, `graph_changed`) to the dashboard, so the Board still moves.

The writer must checkpoint for changes to show. The daemon does so after every sync batch, and the demo replay after every write.

## Security rules

| Setting | Effect |
|---|---|
| `SDD_PUBLIC_QUERY=guarded` (default) | the Query tab runs any read-only Cypher through the query guard: write clauses and `CALL` rejected, variable-length patterns at most `*..4`, 100 rows, 5 s, in a killable worker process with a memory cap (`SDD_QUERY_MEMORY_MB`, default 1024) |
| `SDD_PUBLIC_QUERY=presets` | the Cypher box becomes display-only; `POST /api/query` answers 400 `query_rejected`; only the named presets run |
| Rate limits (built in) | 60 requests/min per IP for `/api/query`, 600/min for everything else; over the limit, 429 `rate_limited` with `Retry-After` |
| `SDD_TRUSTED_PROXY_NET` | a CIDR (e.g. your Docker network). Only requests from it may set the client IP through `CF-Connecting-IP` or `X-Forwarded-For`. Everyone else is limited by their socket address |
| `PUBLIC_BASE_URL` | the public URL, shown in the dashboard footer |
| `SDD_PROJECT_NAME` | the name `/api/health` reports and the header shows (default: the project folder's name) |

Every response carries `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`. Errors never include stack traces or paths outside the project. Public mode has no token, Host or Origin check: it serves public data only and has no write route.

**What becomes public:** everything in the graph: spec text, task titles and notes, deviation text, file paths, commit subjects and author **names** (never emails). Don't serve a repo whose docs you wouldn't publish.

## Hosting it on the internet

This repo's `deploy/` folder is a working example: a replay writer, the public server with the store volume mounted read-only, and a Cloudflare tunnel, in an isolated Compose project with a fixed subnet. Containers run as a non-root user with a read-only root file system, all capabilities dropped and CPU/memory limits. Read `deploy/README.md` before copying it. The tunnel token goes only in `deploy/.env`, which is gitignored.

Put a proxy with TLS in front (Cloudflare, Caddy, nginx). The server itself speaks plain HTTP. Add your own rate limit for `POST /api/query` at the proxy, and never cache `/api/*`.
