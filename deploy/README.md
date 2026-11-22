# Home hosting

The hosted demo runs three containers as the Compose project `relate-sdd`: `replay` (simulated agents working the Courtside sample in a loop, the only writer), `public` (a read-only server that follows the replay's store) and `cloudflared` (a remotely managed Cloudflare tunnel that publishes one hostname). Nothing is opened on the router, and the stack has no database, no accounts and no write path. Background: [SPEC-11 §7](../docs/specs/SPEC-11-deployment-and-demo.md#7-home-hosting) and [SPEC-09 §4–5](../docs/specs/SPEC-09-security.md#4-public-mode).

You need a server with Docker and Compose v2, and (for the public URL) a Cloudflare account with a domain.

## 1. Get the repo and configure it

```bash
git clone <this repo> relate-sdd && cd relate-sdd/deploy
cp .env.example .env
```

Edit `.env`:

- `PUBLIC_BASE_URL`: the hostname you will publish, for example `https://sdd-demo.example.com` (shown in the dashboard footer).
- `COMPOSE_SUBNET`: a subnet no other stack on the server uses (the default `172.31.0.0/24` is free unless you changed it). `public` trusts `CF-Connecting-IP` **only** from this network, so nobody on the LAN can choose the IP the rate limiter sees.
- Leave `SAMPLE=courtside`, `SDD_REPLAY_*` and `TZ` as they are unless you want a different pace. `SDD_PUBLIC_QUERY=presets` turns the Query tab into presets only.
- `TUNNEL_TOKEN` stays empty until step 3. Never commit `.env`.

## 2. Build and start

```bash
docker compose build
docker compose up -d
docker compose ps        # replay and public should become "healthy" (the first start takes up to two minutes)
```

### Check it

```bash
curl -s http://127.0.0.1:8780/api/health
# {"ok":true,"mode":"public", ...}

curl -so /dev/null -w '%{http_code}\n' http://127.0.0.1:8780/mcp
# 404

curl -so /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8780/api/sync
# 403
```

Open `http://127.0.0.1:8780` on the server: the Board should show tasks moving every few seconds. If `PUBLIC_BIND` is not loopback, use that address.

## 3. Create the tunnel

In Cloudflare Zero Trust go to Networks, then Tunnels, and create a tunnel (connector type Docker). Copy its token into `TUNNEL_TOKEN` in `.env`, then:

```bash
docker compose --profile tunnel up -d
```

## 4. Publish the hostname

In the tunnel, add a Public hostname: `sdd-demo.example.com` with service `http://public:8780`.

If the server already runs a shared `cloudflared` for other apps, skip the `tunnel` profile and point that tunnel at `http://<server-host>:8780` instead (set `PUBLIC_BIND` to an address it can reach), or attach its container to this stack's network.

## 5. Cloudflare rules

- Rate-limit `POST /api/query` (for example 30 per minute per IP). The server also limits itself (60 per minute for `/api/query`, 600 per minute for everything else).
- Cache the dashboard's assets only with a rule that respects the origin's headers (Cloudflare: "Use cache-control header if present"). Every dashboard file is sent with `Cache-Control: no-cache`, so the CDN and browsers keep a copy but revalidate it by ETag before using it (a cheap 304) and a deploy shows at once. A rule that forces its own TTL by extension (`.js`, `.css`) serves stale files after a deploy; if that happens, purge the cache and fix the rule. The dashboard is served at `/`, not under a `/static/` prefix. Never cache `/api/*`.
- Turn on Bot Fight Mode.

`/api/events` (server-sent events) passes through tunnels. If a proxy buffers it, the dashboard falls back to polling.

## 6. Update

```bash
git pull && docker compose build && docker compose up -d
```

The replay resets itself every `SDD_REPLAY_MAX_MIN` minutes (or when the scripted milestones are done), so no data migration is needed. Reset the demo by hand with `docker compose restart replay`.

## Notes

- `replay` and `public` run as uid 10001 with a read-only root file system, `tmpfs` at `/tmp`, all capabilities dropped and CPU and memory limits (1 CPU / 768 MB and 1 CPU / 512 MB). Only `public` publishes a port, on `PUBLIC_BIND` (loopback by default).
- The volume `demo-data` holds the replay's working copy of the sample. `public` mounts it read-only.
- Logs: `docker compose logs -f replay public`.
