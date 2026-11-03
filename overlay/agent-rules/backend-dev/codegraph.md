# codegraph — Query the Index Before and While Editing Code

codegraph (`@colbymchenry/codegraph` 1.6.2) is a SQLite knowledge graph of every symbol, edge and
file in a project, built by an AST parse. Reads are sub-millisecond and the index follows your
writes about a second later, through the MCP server's file watcher.

The MCP server sends its usage guide in its `initialize` response. Claude Code passes it to main
sessions and subagents alike; kiro-cli and agy may drop it, and a server started outside an indexed
project sends only a short variant. This file is that guide for every case. Where the server's guide
is also in your context, both say the same.

## One tool: `codegraph_explore`

`@codegraph` lists one tool. `codegraph_node`, `codegraph_search`, `codegraph_callers`,
`codegraph_callees`, `codegraph_impact`, `codegraph_files` and `codegraph_status` are not exposed:
their output already arrives inside an explore answer, and the CLI covers them (last section).

| Parameter | Use |
|---|---|
| `query` | A natural-language question, or a bag of symbol/file names (`"IsolationError resolve_npm_pins install_wrappers"`) |
| `projectPath` | Absolute path to the project or any directory inside it; codegraph uses the nearest index at or above it. Always pass it — omitted, the answer comes from whichever project the server opened first |
| `maxFiles` | Cap on files returned with source (default 12) |

Pass the root of the checkout you are working in. When that is a git worktree, pass the
worktree path, not the main clone: each worktree has its own index.

One call returns the verbatim, line-numbered source of the relevant symbols grouped by file (the
same `<n>\t<line>` shape `Read` gives), the call path between them — dynamic-dispatch hops
included — and a blast-radius summary of what depends on them.

## How to query

- **"How does X work", architecture, a bug, "where is X", surveying an area** → one
  `codegraph_explore` with the question in natural language.
- **A flow ("how does X reach Y")** → name the symbols at both ends in one query. Do not rebuild
  the path by hand.
- **A file or symbol you are about to change** → put its name or path in `query` before editing.
  You get its current source plus its callers, so you edit with the blast radius in view.
- **Not enough?** Call again with more specific names.

## Reading the answer

- **Treat the returned source as already read.** Do not re-open those files, and do not re-verify
  the source with grep: it comes from a full AST parse.
- **The blast-radius summary is approximate.** Its caller count is graph edges and can exceed the
  distinct call sites, and `in <file>` names one file even when the callers span several, tests
  included. The count in the `codegraph callers` header behaves the same; its list does not. Before
  a rename or signature change, list the call sites with `codegraph callers <symbol>` (or
  `codegraph impact`) and confirm them with grep.
- **In Claude Code, `Edit` still needs a `Read` of that file in this conversation** — the tool
  enforces it. Read only the lines you will change (`offset`/`limit`), using the line numbers
  codegraph gave you.
- **`⚠️ Some files referenced below were edited since the last index sync`** — the listed files are
  pending re-index; read those. Every file not listed is current.
- **`⚠️ CodeGraph auto-sync is DISABLED`** — the whole index is frozen. Until it is resolved, read
  files directly to confirm anything that may have changed.
- **`⚠ changed on disk after the last index sync`** on a file — its source was omitted or shown in
  full from disk. When omitted, read that file; other line numbers in it may be shifted.
- **`Already sent earlier in this conversation`** — the copy already in your context is current.
  Scroll back to it; do not re-fetch or read the file.
- **A worktree-mismatch notice** — the index answering belongs to another working tree. Re-run with
  `projectPath` set to your worktree.

## When codegraph cannot answer

- **Project not indexed** (no `.codegraph/`): where the host runs a session-start hook, it builds the
  first index of the repo the session opened in — a new worktree included. For any other repo, or a
  host without hooks (agy), run `~/.kiro/bin/archirelik/ensure-codegraph.sh <repo>` once: it
  builds the index in the background. Use `read`/`grep` until it finishes; the server picks it up
  without a restart.
- **Not a correctness check.** The graph is structure: the type checker, the linter and the test
  suite still own the verdict.
- **Ambiguous names** resolve best-effort, so a call may return several candidates.
- **Not indexed by design**: anything in `.gitignore`, dependency and build directories
  (`node_modules`, `.venv`, `dist`, `build`…), files over 1 MB, and config or docs that carry no
  symbols. Read those.

## CLI

For what the MCP tool does not return, prefix with `rtk` like any other shell command and pass
`-p <worktree>` (or the path argument) when you are not at its root:

| Command | Use |
|---|---|
| `git diff --name-only \| codegraph affected --stdin --quiet` | Test files transitively affected by the changed sources — run those instead of the whole suite |
| `codegraph impact <symbol>` | Blast radius before a rename or signature change |
| `codegraph callers <symbol>` / `callees <symbol>` | One hop of the call graph, as a list |
| `codegraph status` | Index statistics. `Journal:` other than `wal` means the project sits on a filesystem (WSL `/mnt/c`) where reads block on writes |
| `CODEGRAPH_DIR=.codegraph-wsl codegraph init --yes` | Only for a repo on a Windows drive (`/mnt/c/…`) whose `.codegraph/` Windows built: WSL needs its own index there, and a shared one fails with a SQLite I/O error. A repo first indexed from WSL already gets `.codegraph-wsl/` by itself |
| `codegraph unlock` | Only when indexing reports a stale lock file |

Never run `codegraph daemon` (an interactive picker), `uninit`, `index` or `install`: the first
blocks the shell and the others change the project or the user's agent config.
