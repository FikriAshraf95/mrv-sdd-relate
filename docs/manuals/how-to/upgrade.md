# Upgrade to a new version

> **For:** anyone running SDD Graph on their repo when a new version comes out.

## 1. Let agents finish

Upgrading restarts the daemon. Claims survive a restart, but agents mid-call will see connection errors. Let running workers finish or release their tasks first (`sdd status` lists live claims).

## 2. Stop the daemon

Ctrl+C in its terminal, or `docker stop sdd-daemon`. On shutdown it drains the write queue, checkpoints and removes `.sdd/daemon.json`.

## 3. Install the new version

**uv:**

```bash
uv tool upgrade relate-sdd
# or, to move to a specific tag or commit:
uv tool install --force --python 3.13 git+https://github.com/FikriAshraf95/mrv-sdd-relate.git@<tag-or-commit>
sdd --version
```

**Docker:** in your clone of this repo:

```bash
git pull
docker build --target runtime -t relate-sdd/sdd:local .
docker rm sdd-daemon     # then re-run the `docker run -d --name sdd-daemon …` command from Install
```

## 4. Check the schema version

```bash
sdd info
```

Look at the line `schema version  1 (store: 1)`. The first number is what the code expects; the second is what your store was built with.

- **Equal:** start the daemon. You're done.
- **Different:** there is no automatic migration. Rebuild the store from your files with `sdd sync --reset` ([what that drops](rebuild-the-graph.md#what-you-lose): claims, agents, events). Then start the daemon.

## 5. Refresh the generated files

New versions may update the agent skill or the default config comments. Compare and take what you want:

```bash
sdd init            # reports "kept" for files that exist; changes nothing
sdd init --force    # rewrites .sdd/config.toml, .sdd/.gitignore, the sdd entry in .mcp.json and SKILL.md
```

`--force` replaces your `.sdd/config.toml` with freshly detected globs, so re-apply any custom keys afterwards (check `git diff`). Other servers in `.mcp.json` are always kept.

## 6. Start and verify

```bash
sdd daemon
sdd doctor       # new parser versions may report new warnings
sdd status
```

If `sdd doctor` shows a new warning code, look it up in [Repo format](../reference/repo-format.md#warning-codes).
