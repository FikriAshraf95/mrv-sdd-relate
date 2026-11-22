# SDD Graph manual

SDD Graph (package `relate-sdd`, command `sdd`) turns a spec-driven repo into one live [Relate](https://relatedb.ai/) graph. AI agents use the graph over MCP and people use it through a dashboard, so nobody has to re-read whole Markdown files to find what a task needs.

This manual follows the [Diátaxis](https://diataxis.fr/) layout. Tutorials teach you by doing, how-to guides solve one problem each, reference pages list facts, and explanation pages say why things work the way they do. Start with the row that matches you.

## Start here

| You are… | Your question | Read |
|---|---|---|
| **A curious visitor or judge** | "What is this, and is it worth my time?" | [Introduction](01-introduction.md) → [Quick start](02-quick-start.md) (5 minutes, Docker only) |
| **A developer adopting it** | "How do I use it on my own repo?" | [Concepts](03-concepts.md) → [Tutorial: your own repo](04-tutorial-your-repo.md) → [How-to guides](#how-to-guides) |
| **An AI agent (Claude Code)** | "Which tools do I call, and in what order?" | [Guide for agents](agents.md) → [MCP tools reference](reference/mcp-tools.md) |
| **A contributor** | "How do I build, test and extend it?" | [Contributing](contributing.md) → [Concepts](03-concepts.md) → the specs in [docs/specs/](../specs/) |

## Contents

### Learn
1. [Introduction](01-introduction.md): the problem, what SDD Graph does, what it isn't, benchmark numbers
2. [Quick start: try the sample](02-quick-start.md): `docker compose up` and a guided tour of the Courtside sample
3. [Concepts](03-concepts.md): source of truth, the single writer, the graph, claims, context packets, write-back, deviations
4. [Tutorial: adopt it on your own repo](04-tutorial-your-repo.md): one path from install to your first milestone run by agents

### How-to guides
- [Install `sdd`](how-to/install.md) (uv, or Docker with no Python on the host)
- [Write task lines that get small context packets](how-to/link-tasks-to-sections.md)
- [Run parallel subagents on one milestone](how-to/parallel-subagents.md)
- [Log a deviation](how-to/log-a-deviation.md) (and what write-back changes in your files)
- [Handle a spec change from a client or PM](how-to/handle-a-spec-change.md)
- [Free a stuck claim when an agent crashed](how-to/free-a-stuck-claim.md)
- [Find what a change affects (`impact`) and why a file exists (`explain`)](how-to/impact-and-explain.md)
- [Rebuild the graph from scratch](how-to/rebuild-the-graph.md)
- [Snapshot the graph and share it](how-to/snapshot-and-share.md) (`.rl`, JSON, Cypher)
- [Export diagrams and the CLAUDE.md status block](how-to/export-diagrams-and-status.md)
- [Measure the savings on your own repo](how-to/measure-savings.md) (`sdd bench`)
- [Run the read-only public mode](how-to/public-mode.md)
- [Use a bearer token and remote access safely](how-to/token-and-remote-access.md)
- [Upgrade to a new version](how-to/upgrade.md)

### Reference
- [CLI](reference/cli.md): every command, flag, exit code and an example
- [MCP tools](reference/mcp-tools.md): parameters, return shape, errors, example calls
- [HTTP API](reference/http-api.md): endpoints, SSE events, status codes
- [Error codes](reference/error-codes.md): one table across MCP, HTTP and CLI
- [Configuration](reference/configuration.md): `.sdd/config.toml` keys and environment variables
- [Repo format and parsing rules](reference/repo-format.md): headings, task IDs, *Read first*, deviation files
- [Graph schema](reference/graph-schema.md): labels, relationships, properties that matter for queries
- [Example Cypher queries](reference/cypher-examples.md): for the Query tab, `sdd query` and the `query` tool

### For agents, troubleshooting, and the rest
- [Guide for agents](agents.md): the protocol, a copy-paste CLAUDE.md block, the rules
- [Troubleshooting and FAQ](troubleshooting.md): organised by the symptom you see
- [Cheat sheet](cheat-sheet.md): the 10 commands and 10 tools you use daily, on one page
- [Limitations and roadmap](limitations-and-roadmap.md): what it doesn't do yet
- [Contributing](contributing.md): dev container, gates, the rules that must never break

## Conventions in this manual

- Commands are shown as `sdd …`. If you run SDD Graph in Docker, prefix them as described in [Install](how-to/install.md#option-b-docker-no-python-on-the-host).
- `M05a.3` is a task ID, `M05a` a milestone, `SPEC-03 §2` a spec section, `D006` a deviation. The examples use the bundled **Courtside** sample (`samples/courtside/`), an invented court-booking app.
- The specs in [docs/specs/](../specs/) are the source of truth for this tool. When this manual and a spec disagree, the spec wins, and the manual has a bug.
