# RTK — Shell Output Compression

rtk condenses command output before it reaches your context. kiro-cli has no hook that rewrites
commands — nothing prefixes for you — so every un-prefixed shell call pays the full raw output.
(Under Claude Code a hook adds it; the prefix is idempotent, so typing it is safe in both hosts.)

## The rule

Prefix every shell command (the `shell` tool, `execute_bash` under CLI 2.x) with `rtk`, and keep
the prefix inside chains:

```bash
rtk git status --short
cd ~/projects/my-agent && rtk git log --oneline -5
uv run rtk pytest tests/ -v
```

Commands in other rules, skills, `AGENTS.md` and READMEs are written without the prefix for
readability. Add it when you run them. Commands rtk has no filter for run unchanged, so the prefix
never alters behaviour or exit code.

## This agent's commands

| Instead of | Run |
| --- | --- |
| `uv run pytest …`, `uv run ruff …`, `uv run mypy …` | `uv run rtk pytest …`, `uv run rtk ruff …`, `uv run rtk mypy …` — the prefix goes after the runner |
| `git <anything>` | `rtk git <anything>` |
| `docker …`, `kubectl get/logs …`, `ls -R`, `find` | prefix directly |
| `terraform fmt/validate/test`, `cdk`, `aws …` | `rtk err <command>` — no filter exists; `err` keeps only error and warning lines. On a failure, re-run it raw to see the file, line and context |

`rtk hook check "<command>"` prints what a command becomes — use it instead of guessing coverage.

Searching code and reading files stays with the native `grep`, `glob` and `read` tools, never shell
`grep`/`cat`/`sed -n`. rtk does not make the shell the right tool for that.

## Where the prefix costs more than it saves

- **Output you must read line by line.** A `git diff` you are reviewing, or a failing test log you
  must quote back. `git show HEAD:path` is byte-identical under rtk and safe; a diff under review is
  not.
- **Output another program consumes** — a pipe, or a capture into a variable (`V=$(...)`). rtk groups
  and truncates, corrupting the value the script reads.
- **Interactive or long-running commands**: `kubectl port-forward`, `docker compose up`, anything
  with `-it`.

## Escape hatches

`rtk proxy <cmd>` re-runs unfiltered when a result looks unusable (empty where output was expected,
contradicting the exit code, garbled). `RTK_DISABLED=1 <cmd>` skips rtk for one command. Truncated
output states its own recovery path (`rtk recall <hash>`); otherwise treat condensed output as the
complete result and do not re-run it.
