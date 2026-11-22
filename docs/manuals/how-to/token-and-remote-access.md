# Use a bearer token and remote access safely

> **For:** anyone who wants a token on the local daemon, or agents or browsers on another machine.

## The defaults

The daemon binds to **`127.0.0.1:8770`** and needs no token: only processes on your machine can reach it. Three more checks always run:

- **Host check.** Every request's `Host` header must be a loopback name (`localhost`, `127.0.0.1`, `[::1]`, any port) or a host listed in `SDD_ALLOWED_HOSTS`. Otherwise you get 403 `forbidden_host`. This stops DNS-rebinding attacks, where a web page's domain re-resolves to 127.0.0.1.
- **Origin check.** Write endpoints and `/mcp` reject a request whose `Origin` header isn't the daemon's own origin (403 `forbidden_origin`), so a web page you visit can't post to your daemon. Requests with no `Origin` (Claude Code, the CLI, curl) pass.
- **Write-back stays inside the project root.** A path outside it is `invalid_input`.

## Add a token (local)

Set `SDD_TOKEN` in the daemon's environment:

```bash
export SDD_TOKEN="$(openssl rand -hex 32)"
sdd daemon
```

Now every `/api` and `/mcp` request needs `Authorization: Bearer <token>`, or gets 401 `unauthorized`. `daemon.json` stores only the token's SHA-256.

**Claude Code.** Run `sdd init --force` with `SDD_TOKEN` set (or edit `.mcp.json` by hand) so the `sdd` entry gets a header that names the variable, not the value:

```json
{ "mcpServers": { "sdd": {
    "type": "http", "url": "http://localhost:8770/mcp",
    "headers": { "Authorization": "Bearer ${SDD_TOKEN}" } } } }
```

Claude Code expands `${SDD_TOKEN}` from its environment, so the token itself is never written to a file. Start Claude Code from a shell where `SDD_TOKEN` is set. (`--force` replaces the files `init` writes. To change only `.mcp.json`, edit it by hand.)

**The CLI** reads `SDD_TOKEN` from the environment and sends it.

**The dashboard.** Its static files hold no data and load without a token. On the first 401 it asks for the token once, keeps it in `sessionStorage` (this tab only, gone when the tab closes) and sends it on every `/api` call. The token never goes in a URL or a cookie. Browsers can't add headers to the live event stream, so with a token set, the Board polls every 5 s instead (the indicator says `polling`).

**curl:**

```bash
curl -H "Authorization: Bearer $SDD_TOKEN" http://127.0.0.1:8770/api/status
```

## Remote access

Binding anything other than loopback **outside a container** requires both:

```bash
export SDD_ALLOW_REMOTE=1
export SDD_TOKEN="…long random…"
sdd daemon --host 0.0.0.0
```

Without both, the daemon refuses to start. Inside a container, `SDD_ALLOW_REMOTE=1` alone is enough, because the container must bind `0.0.0.0` and the Compose files publish the port on `127.0.0.1` only. If you publish it more widely, set a token.

Also list the host name clients will use, or the Host check rejects them:

```bash
export SDD_ALLOWED_HOSTS="devbox.internal,devbox.tailnet.example"
```

### Recommended setups

| Setup | How |
|---|---|
| **SSH tunnel** (best for one person) | Keep the daemon on loopback. From the other machine: `ssh -N -L 8770:127.0.0.1:8770 you@devbox`. Clients use `http://localhost:8770` as usual, with no remote binding at all |
| **Private network** (Tailscale, WireGuard, LAN) | `SDD_ALLOW_REMOTE=1`, a long `SDD_TOKEN`, `SDD_ALLOWED_HOSTS=<the name clients use>`, bind to the private interface's address rather than `0.0.0.0` where you can |
| **The internet** | Don't expose the daemon. It has write routes and MCP. Serve a read-only copy with [public mode](public-mode.md) behind a TLS proxy instead |

The daemon speaks plain HTTP. Over any network you don't fully trust, put TLS in front (SSH, a VPN, or a reverse proxy), or the token travels in the clear.

## Keep secrets out of files

- `SDD_TOKEN` (and, for the benchmark, `ANTHROPIC_API_KEY`) belong in your environment or an untracked `.env`, never in `.mcp.json`, `.sdd/config.toml`, scripts or commits.
- The daemon never logs the token or full Markdown text; logs name section IDs only.
- Rotate a token by restarting the daemon with a new value. Open dashboard tabs ask again on their next 401.
