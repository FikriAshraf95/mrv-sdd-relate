# Install `sdd`

> **For:** anyone putting SDD Graph on their own repo. SDD Graph isn't on PyPI yet, so you install it from this git repository.

Two options. Both give you the same `sdd` command.

| | Option A: uv | Option B: Docker |
|---|---|---|
| Needs on your machine | [uv](https://docs.astral.sh/uv/) (it fetches Python 3.13 itself) | Docker |
| File watching | native events (instant) | polling (1 s for docs, 10 s+ for code) |
| `sdd snapshot` `.rl`/JSON copies | only if you also install the [Relate CLI](https://relatedb.ai/) | only in the dev image (see below) |
| Best for | macOS, Linux | Windows, or "nothing on my host" |

## Option A: uv

```bash
uv tool install --python 3.13 git+https://github.com/FikriAshraf95/mrv-sdd-relate.git
sdd --version
```

Expected output:

```
sdd 0.1.0
relate-db 1.2.0
```

Requirements: Python 3.13 exactly (uv handles it), and a `relate-db` ≥ 1.2 wheel for your platform. There is no wheel for musl-based systems such as Alpine. If the install fails on `relate-db`, use option B.

To pin a version, add `@<tag or commit>` to the URL. To upgrade, see [Upgrade](upgrade.md).

**Optional, for `sdd snapshot`:** the `.rl` single-file copy and the JSON copy can only be made by the `relate` CLI (the Python package can't). Install it with the official script from <https://relatedb.ai/> and make sure `relate` is on your `PATH`. Without it, `sdd snapshot` writes only the directory copy and reports the other two as `skipped`.

## Option B: Docker (no Python on the host)

Build the runtime image once from a clone of this repo:

```bash
git clone https://github.com/FikriAshraf95/mrv-sdd-relate.git
cd mrv-sdd-relate
docker build --target runtime -t relate-sdd/sdd:local .
```

The image's entry point is `sdd`, so `docker run … relate-sdd/sdd:local <command>` runs `sdd <command>`.

### Run the daemon on your repo

From **your** repo's root:

```bash
docker run -d --name sdd-daemon \
  -v "$PWD":/repo -w /repo \
  -p 127.0.0.1:8770:8770 \
  -e SDD_ALLOW_REMOTE=1 \
  relate-sdd/sdd:local daemon --host 0.0.0.0
```

- `-p 127.0.0.1:8770:8770` publishes the port **on loopback only**, so nothing outside your machine can reach it.
- `--host 0.0.0.0` plus `SDD_ALLOW_REMOTE=1` lets the daemon accept the published connection from inside the container. That combination is allowed without a token **only inside a container**, because the port is published on loopback ([security rules](token-and-remote-access.md)).
- Watching uses polling automatically inside Docker. That's required on Windows and macOS, because native file events don't cross a bind mount.
- `.mcp.json` from `sdd init` points at `http://localhost:8770/mcp`, which reaches the published port. Nothing else to change.

**On Linux**, add `--user "$(id -u):$(id -g)"` so the files the daemon writes back (ticked boxes, deviation files) are owned by you, not by the image's user (uid 10001).

**In Git Bash on Windows**, prefix commands that pass container paths with `MSYS_NO_PATHCONV=1`. **In PowerShell**, use `-v "${PWD}:/repo"`.

### Run other commands

While the daemon container runs, run commands **inside it**, so they find the daemon and go through its API:

```bash
docker exec sdd-daemon sdd status
docker exec sdd-daemon sdd impact bookings
docker exec sdd-daemon sdd claim M02.1 --agent me
```

When no daemon runs, use a throwaway container:

```bash
docker run --rm -it -v "$PWD":/repo -w /repo relate-sdd/sdd:local init
docker run --rm -it -v "$PWD":/repo -w /repo relate-sdd/sdd:local ids --write
docker run --rm     -v "$PWD":/repo -w /repo relate-sdd/sdd:local doctor
```

A shell alias saves typing:

```bash
alias sdd='docker run --rm -it -v "$PWD":/repo -w /repo relate-sdd/sdd:local'
```

Commands that write Markdown or open the store for writing (`sync`, `ids --write`) refuse with `daemon_running` while a daemon owns the store. Stop the daemon first (`docker stop sdd-daemon`), run them, then start it again (`docker start sdd-daemon`).

### The dev image (contributors, and `.rl` snapshots)

The repo's `docker-compose.dev.yml` builds a `dev` image that also contains uv, git and the `relate` CLI. Use it when you work on SDD Graph itself, or when you need `sdd snapshot` to write `.rl` and JSON copies. See [Contributing](../contributing.md).

## Check the install

```bash
sdd --version          # sdd and relate-db versions
sdd --help             # every command
```

Then continue with the [Tutorial](../04-tutorial-your-repo.md#step-2-check-your-repo-layout).
