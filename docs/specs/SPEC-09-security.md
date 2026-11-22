# SPEC-09 — Security

> **Status:** v1 (2026-11-21) · **Owner of:** binding and tokens, the query guard, public mode, resource limits, what the hosted demo may expose

## 1. Threat model

- **Local daemon:** the risk is another local process or a web page in the user's browser writing to the graph or the Markdown. Mitigations: loopback bind, optional token, Origin checks.
- **Hosted demo:** the internet. The risk is writes, resource exhaustion through heavy Cypher, and reaching the home server's other services. Mitigations: a separate read-only process, a query guard, limits, an isolated container network, Cloudflare in front.
- Out of scope: multi-user auth, untrusted Markdown authors (the repo owner writes the docs).

## 2. Local daemon

1. Binds `127.0.0.1` by default. Binding anything else requires `SDD_ALLOW_REMOTE=1` **and** `SDD_TOKEN`, or the daemon refuses to start. **Exception inside a container** (`/.dockerenv` exists): `SDD_ALLOW_REMOTE=1` alone is enough, because the container must bind `0.0.0.0` and our Compose files publish the port on `127.0.0.1` only ([SPEC-11 §2](SPEC-11-deployment-and-demo.md#2-compose)).
2. `SDD_TOKEN` (optional locally): when set, every `/mcp` and `/api` request needs `Authorization: Bearer <token>`, or gets 401 `unauthorized`. `daemon.json` stores only its SHA-256. **The dashboard under a token:** its static files hold no data and need no token. On the first 401 the dashboard asks for the token once, keeps it in `sessionStorage` (this tab only, gone when it closes) and sends it as the header on every `/api` call. `EventSource` cannot send headers, so with a token set the Board uses its polling fallback ([SPEC-07 §3](SPEC-07-dashboard-and-api.md#3-live-events)). The token never goes in a URL or a cookie.
3. **Host check (DNS rebinding):** every request's `Host` header must name a loopback host (`localhost`, `127.0.0.1`, `[::1]`, any port) or a host listed in `SDD_ALLOWED_HOSTS`; otherwise 403 `forbidden_host`. Without it, a web page whose domain re-resolves to 127.0.0.1 could read the whole API, because reads have no Origin check.
4. **Write endpoints and `/mcp` reject requests whose `Origin` header is not the daemon's own origin** (stops a web page from posting to localhost) with 403 `forbidden_origin`. "Own origin" is `http://<the request's Host header>`, which the Host check has already limited to loopback, so it works behind a Compose port mapping. Requests without `Origin` (Claude Code, the CLI) are allowed.
5. Write-back only edits files inside the project root, resolved with `Path.resolve()`. A path outside it is `invalid_input`.
6. Logs never contain the token or full Markdown text; section IDs only.

## 3. Query guard

Used by the `query` tool, `POST /api/query` and `sdd query`.

1. **Tokenise** the statement (skipping strings and comments) and reject it with `query_rejected` if it contains `CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH`, `REMOVE`, `DROP`, `LOAD`, `FOREACH`, `CALL`, `USE`, `IN TRANSACTIONS`, or more than one statement.
2. **Run it in a transaction that is always rolled back** (`autocommit = False` … `rollback()`), so a write that slips past step 1 still changes nothing. This layer is load-bearing: a `read_only=True` connection accepts a write inside a transaction and refuses it only at commit (O11). It runs on a `read_only=True` snapshot connection where one is available (always in public mode; in the daemon if open item O12 allows, [SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)), a third layer that also keeps it off the writer's lock.
3. Cap rows at 100 (`truncated: true` beyond). Time limit 5 s: `relate-db` offers no per-query timeout (O4, closed), so the query runs on a worker thread and the request fails with `query_timeout` after 5 s while the result is discarded. Python cannot kill that thread, so at most **one** guarded query runs at a time per process; a second one waits up to 5 s, then gets `query_timeout`.
4. Variable-length patterns without an upper bound (`*`, `*2..`) are rejected **in every mode**, daemon included, because a runaway query blocks claims; the maximum is `*..4`.
5. `SDD_PUBLIC_QUERY` = `guarded` (default) or `presets` (only preset names run; the box is display-only).

> **DEVIATION:** see [D006](../deviations/D006-guarded-queries-run-in-a-killable-worker-process-with-a.md) — Guarded queries run in a killable worker process with a memory cap

## 4. Public mode

`sdd public` is a different process from the daemon:
- Opens the store with `read_only=True` and reopens when `manifest.json` changes ([SPEC-01 §1](SPEC-01-architecture.md#1-process-model)).
- Serves only the endpoints marked public in [SPEC-07 §2](SPEC-07-dashboard-and-api.md#2-endpoint-index). Write endpoints return 403 `read_only`; `/mcp` is not mounted at all (404), and any non-GET request to an unknown path is 404 too. It serves public data only and has no write route, so it has **no Host, token or Origin check** (those belong to the daemon, [§2](#2-local-daemon)). It **ignores `agent` parameters** (some read paths would write agent state). With `SDD_PUBLIC_QUERY=presets`, `POST /api/query` answers 400 `query_rejected` ("Only the named presets run on this server."); presets still run through `/api/presets/{name}`.
- Rate limit in-process: 60 requests/min per IP for `/api/query`, 600/min for the rest (Cloudflare adds its own rules); over the limit, 429 `rate_limited` with `Retry-After`. The client IP comes from `CF-Connecting-IP` (then `X-Forwarded-For`) **only** for requests from the trusted proxy network `SDD_TRUSTED_PROXY_NET` (set to `COMPOSE_SUBNET` in [SPEC-11 §7](SPEC-11-deployment-and-demo.md#7-home-hosting)); otherwise from the socket. Uvicorn runs with `proxy_headers=False`, so it never rewrites the client address itself.
- Response headers: `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- Error responses never include stack traces or file system paths outside the project (an unhandled error answers a bare 500 `Internal Server Error`, with the headers above).

## 5. Hosted demo infrastructure

- Containers run as a non-root user with a read-only root file system (the store volume excepted, plus a `tmpfs` at `/tmp`; `PYTHONDONTWRITEBYTECODE=1`), `cap_drop: [ALL]`, `no-new-privileges`, CPU and memory limits (`public`: 1 CPU, 512 MB; `replay`: 1 CPU, 768 MB).
- The hosted stack runs as its own Compose project (`relate-sdd`) with its own fixed subnet, separate from the server's other stacks. Only `public` publishes a port, on `PUBLIC_BIND` (loopback by default). `replay` and `cloudflared` publish none.
- TLS ends at Cloudflare; Relate's own servers are plaintext and are not used for the public demo.
- The replay writer works on a copy of the sample project in a volume, never on the repo checkout.

## 6. Acceptance checks

1. Outside a container, the daemon refuses to start with `--host 0.0.0.0` unless `SDD_ALLOW_REMOTE=1` and `SDD_TOKEN` are set; inside one, `SDD_ALLOW_REMOTE=1` is enough.
2. With `SDD_TOKEN` set, `/api/status` without the header returns 401; with it, 200. `/` and the dashboard's static files still return 200, and the dashboard, given the token once, loads the Board (by polling).
3. `POST /api/tasks/M01.1/claim` with `Origin: https://evil.example` returns 403.
4. The guard rejects `MATCH (n) DETACH DELETE n`, `CREATE (:X)`, `MATCH (n) SET n.x = 1`, `CALL db.labels()`, and two statements separated by `;`; it accepts `MATCH (n:Task) RETURN n.id LIMIT 5`.
5. A write that bypasses the tokenizer (simulated in a test by disabling step 1) leaves the store unchanged.
6. A query running longer than 5 s returns `query_timeout`, and the server stays responsive.
7. In public mode, `/mcp` returns 404 and every write endpoint returns 403.
8. A daemon request with `Host: evil.example` returns 403 `forbidden_host`; `Host: localhost:8770` with `Origin: http://localhost:8770` may write.
9. In daemon mode, the guard rejects `MATCH p=(a)-[*]->(b) RETURN p` and accepts `MATCH p=(a)-[*..4]->(b) RETURN p LIMIT 5`.
