# backend-agent-installer

Installs the team [backend-agent][upstream] (`backend-dev` and its subagents) into an existing
`~/.kiro` with an isolated environment, next to any other agent you already have.

Upstream is designed to *be* `~/.kiro`: you clone it there, and its `kiro` launcher exports
`~/.kiro/.env` into every session. This installer leaves `~/.kiro` alone. It clones upstream into
a temp dir, runs upstream's own `install.py` there, and then deploys the result:

- Secrets go to `~/.kiro/bin/backend-dev/.env` (mode 600). No agent JSON holds a credential.
- The local Postgres MCP servers are archirelik's `db_*`, so archirelik must be installed first. Neo4j starts
  through `neo4j-mcp.sh`, which sources that file.
- Skills, prompts and agents read the isolated file instead of `~/.kiro/.env`.
- The agent stays in its own namespace, and every deployed path is recorded in `bin/backend-dev/.manifest`.

## Install

```bash
./install.sh                    # install or re-install
./install.sh --accept-upstream  # only after checking an upstream install.py change
./install.sh --no-sync          # skip the Claude Code / Antigravity render
./install.sh --check            # only check the development tools; installs nothing
./uninstall.sh
```

Requires archirelik, `kiro-cli` (run once), `python3` ≥ 3.11, `git`, `uv`, and SSH access to Bitbucket. The PRO/PRE
workflows also need the `redpoints` CLI (`uv tool install --index-url "$(pip config get global.index-url)" redpoints-cli`), and the shared `kevint` skill needs the kevint CLI (without it the install
warns and continues). The `localdb` skill needs `psycopg2` in your `python3`.

Re-running is safe. Values already in the `.env` are kept, and only empty or placeholder values are
asked for. If you leave a value empty, the install continues and lists it at the end.

Run with `kiro-cli chat --agent backend-dev`, or `--agent backend-pre-verifier` to verify a ticket in PRE.

## What the isolation layer changes

| Upstream | Installed |
|---|---|
| `~/.kiro/.env`, exported by the `kiro` launcher | `~/.kiro/bin/backend-dev/.env` (600); the launcher is never installed (`--skip-wrappers`) |
| `uvx postgres-mcp` servers (`rpc-db`, `auth-db`…) with `DATABASE_URI=${LOCAL_PG_*}` | archirelik's server for the same database (`db_rpc`, `db_auth`…), renamed in tools, allows and permissions; a re-install replaces the old names |
| `uvx mcp-neo4j-cypher` with `${NEO4J_<ENV>_*}` | `neo4j-mcp.sh <ENV>` |
| Scripts reading `os.environ` (`query.py`, `schema_tool.py`, `fill_bamboo.py`) | A loader prepended that reads the isolated `.env` |
| `skills/backend-dev/kevint/` (a team copy) | `~/.kiro/skills/kevint/`, installed or updated on every run by `kevint skill install -p ~/.kiro/skills` and shared with archirelik |
| `skills/backend-dev/bamboohr/` and `BAMBOO_EMAIL` / `BAMBOO_PASSWORD` / `BAMBOO_TOTP_SECRET` | Not installed, and removed from a previous install and from the `.env` |
| `steering/backend-dev/` | `agent-rules/backend-dev/`: the layout the Claude and agy renderers inline as rules |
| `~/.kiro/skills/**` and `~/.kiro/steering/**` resource globs | Scoped to `backend-dev`, as absolute paths |
| A server declared with no tool granted (`searchkeyword-core-db` in `db-searchkeyword`) | Removed: it would hold a Postgres connection nobody can use |
| No `availableAgents` | Each spawning agent registers the subagents its context names, plus their MCP allows (V3 intersects a subagent's rules with its parent's) |
| No code graph | archirelik's `codegraph` server (pinned `@colbymchenry/codegraph`, as in agent-developer) mounted on `backend-dev`, `backend-pre-verifier` and both code reviewers. The orchestrators index the session's repo at start with archirelik's `ensure-codegraph.sh`; usage rules in `overlay/agent-rules/backend-dev/codegraph.md` |
| No rtk | `rtk` checked (and offered for install) as a prerequisite; `overlay/agent-rules/backend-dev/shell-rtk.md` tells every shell-using agent to prefix commands. In Claude Code the `PreToolUse` hook kiro-sync registers rewrites them; kiro-cli discards a hook's stdout, so no kiro hook is installed |
| Agent prompts | A short block saying where the variables live and how to use them in a shell command |
| `agent-rules/backend-dev/**/*.md` resource glob | Expanded to the always-on rules. Rules that apply to one kind of task (`SITUATIONAL_RULES` in `isolate.py`: infrastructure, review comments, rule-change PRs, WSL toolchain, Java toolchain, and the Python rules from the hefesto repos) are deployed but no resource loads them. `backend-dev_index.md`, loaded by every agent and subagent of the family, tells the agent which one to read for the task, as `general_index.md` does for agent-developer. The install stops if the index and the list disagree |

The isolation layer stops in any of these cases:

- an MCP server has a shape it does not know;
- a `${VAR}` or an inline secret is left in an agent JSON;
- a reference to `~/.kiro/.env` is left anywhere;
- a target path exists but this installer did not create it.

## Java toolchain and language server

Agent shells, MCP servers and language servers source no rc file, so sdkman's init in `~/.zshrc` never
reaches them: they would get no `mvn` and the system OpenJDK 21-ea. Step 9 installs, without sudo:

| What | Where |
|---|---|
| Temurin 17 (sdkman default), Maven 3.9.16, Temurin 25 (only runs jdtls) | `~/.sdkman/candidates/` |
| `mvn`: sdkman's Maven with `JAVA_HOME` forced to 17 | `~/.local/bin/mvn` |
| Eclipse JDT LS 1.63.0 (sha256-checked) and lombok 1.18.48 | `~/.local/share/jdtls/` |
| `jdtls`: starts the server on 25 and registers 17 as the project JDK (`java.configuration.runtimes`) | `~/.local/bin/jdtls` |
| Claude Code plugin `jdtls-lsp@claude-plugins-official`, user scope | `~/.claude/plugins/` |
| `.factorypath` and `.kiro/settings/lsp.json` ignored in every repo | `~/.config/git/ignore` |

kiro-cli ships a Java entry that runs `jdtls` from PATH and starts it on the first `code` request,
so it needs no per-repo `/code init`. Index workspaces live in `~/.cache/jdtls/workspaces/`, one per
repo, plus a slot per concurrent server. The `java-toolchain.md` rule tells the agents to use this
`mvn` instead of downloading Maven to `/tmp`. `--check` runs the same verification as the end of an
install: the toolchain from a shell without sdkman, the language server, and every command the
skills call.

## Claude Code and Antigravity

Step 7 renders `backend-dev` and `backend-pre-verifier` with your own `~/.claude/bin/kiro-sync.py`
and `~/.gemini/bin/kiro-to-agy.py`. Both must list them in `ORCHESTRATORS`. If a renderer is missing,
the step skips it.

On first install the agy plugins are created disabled, because enabled plugins share one rule set.
Turn one on with `agy plugin enable backend-dev`. In Claude Code, run the agent with
`~/.claude/bin/backend-dev`.

## Upstream changes

`upstream.lock` pins the validated commit and a fingerprint of upstream `install.py`. A new commit
is just new content. A changed `install.py` stops the install: check that `--skip-wrappers` still
exists and that the script still writes nothing outside the clone except `uv tool install`, then
re-run with `--accept-upstream` and commit the updated lock.

[upstream]: https://bitbucket.rdpnts.com/projects/AIAGENTS/repos/backend-agent
