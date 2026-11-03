# Backend Rules Index

The rules in your resources are always loaded. The files below are situational: read one with your
file-read tool when the task matches its row, not before. When several rows match, read them all.

| When to load | File |
|---|---|
| Touching AWS accounts, environments (DEV/PRE/PRO), clusters, networking or deployment targets | `infrastructure-architecture.md` |
| Changing code in answer to a pull-request review comment | `applying-review-comments.md` |
| Editing a rule, convention or agent-instruction file (`.amazonq/rules/`, `AGENTS.md`, steering, memory-bank) | `rule-change-pr-scope.md` |
| Running git, a build or a search against a repo under `/mnt/<drive>/` | `local-toolchain-filesystem.md` |
| Running `mvn`, checking the JDK, or looking up a Java definition, reference or implementation | `java-toolchain.md` |
| Writing, changing or reviewing Python code | `python-style.md` |
| Growing a Python module or function, splitting one, or adding a facade | `python-structure.md` |
| Writing, changing, moving or reviewing a Python test, or picking which tests to run | `python-testing.md` |

All files are in `~/.kiro/agent-rules/backend-dev/`. A rule in the repo itself (`AGENTS.md`,
`CLAUDE.md`, `docs/rules/`, `.amazonq/rules/`) is more specific and wins where the two differ.
