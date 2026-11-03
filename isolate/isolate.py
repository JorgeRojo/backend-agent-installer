#!/usr/bin/env python3
"""Deploy the backend-agent clone into ~/.kiro with an isolated environment.

Upstream expects to BE ~/.kiro and exports ~/.kiro/.env into every session through
its `kiro` launcher. Here the secrets live in ~/.kiro/bin/backend-dev/.env (0600),
MCP servers start through wrappers that source it, and every upstream file lands in
a backend-dev namespace or a path recorded in the manifest.

Steering is deployed as agent-rules/backend-dev/ and resources as absolute paths:
that is the layout kiro-sync (Claude) and kiro-to-agy (agy) inline as rules.
"""
from __future__ import annotations

import fnmatch
import getpass
import json
import os
import re
import shutil
import sys
from pathlib import Path

AGENT = "backend-dev"
PROJECT_DIR = Path(__file__).resolve().parent.parent
UPSTREAM = Path(os.environ["UPSTREAM_DIR"])
KIRO = Path(os.getenv("KIRO_DIR") or Path.home() / ".kiro")
BIN = KIRO / "bin" / AGENT
ENV_FILE = BIN / ".env"
MANIFEST = BIN / ".manifest"
BIN_TEMPLATES = PROJECT_DIR / "bin-templates" / AGENT

# Upstream tree -> ~/.kiro tree.
CONTENT_DIRS = {f"skills/{AGENT}": f"skills/{AGENT}", f"steering/{AGENT}": f"agent-rules/{AGENT}"}
# Upstream ships its own copy of these; the one installed by the kevint CLI, shared with
# archirelik, replaces it. Value: the path under ~/.kiro that the CLI owns.
SHARED_SKILLS = {"kevint": "skills/kevint/SKILL.md"}
# Upstream content this installer never deploys, with the .env keys only it uses.
EXCLUDED_SKILLS = ("bamboohr",)
EXCLUDED_ENV_KEYS = ("BAMBOO_EMAIL", "BAMBOO_PASSWORD", "BAMBOO_TOTP_SECRET")
EXCLUDED_ENV_COMMENT_RE = re.compile(r"BambooHR|BAMBOO_TOTP_SECRET")
# Agents a user launches; every other upstream agent is a subagent.
ORCHESTRATORS = (AGENT, "backend-pre-verifier")

# Every way upstream spells its env file, in replacement order.
ENV_PATH_FIXES = (
    (".kiro/.env", f".kiro/bin/{AGENT}/.env"),
    ('".kiro" / ".env"', f'".kiro" / "bin" / "{AGENT}" / ".env"'),
    ("\\.kiro\\.env", f"\\.kiro\\bin\\{AGENT}\\.env"),
)
ENV_PATH_LEFT_RE = re.compile(r"""\.kiro["'\s/\\]*\.env""")
TEXT_FIXES = (
    # The upstream `kiro` launcher is not installed.
    ("`kiro --agent ", "`kiro-cli chat --agent "),
    (f".kiro/steering/{AGENT}", f".kiro/agent-rules/{AGENT}"),
    *((f"skills/{AGENT}/{name}/SKILL.md", path) for name, path in SHARED_SKILLS.items()),
)

PLACEHOLDER_RE = re.compile(r"(^|[-_@])your[-_]|^team-|^you@")
SECRET_RE = re.compile(r"(TOKEN|PASSWORD|SECRET|API_KEY)$")
ENV_LINE_RE = re.compile(r"^\s*(#\s*)?([A-Z][A-Z0-9_]*)=(.*)$")
PG_URI_RE = re.compile(
    r"^postgresql://\$\{LOCAL_PG_USER\}:\$\{LOCAL_PG_PASSWORD\}@\$\{LOCAL_PG_URL\}/([A-Za-z0-9_]+)$"
)
NEO4J_VAR_RE = re.compile(r"^\$\{NEO4J_([A-Z]+)_(URI|PASSWORD)\}$")

PROMPT_NOTE = """

<!-- backend-agent-installer:begin -->
Isolated environment: the variables of the team `.env` are NOT exported in your shell. They live in
`~/.kiro/bin/backend-dev/.env`, which the skill scripts and MCP wrappers read themselves.
`SOURCE_REPOS_PATH` is `{source_repos}`. When a command needs one of the other variables expanded
(`$BITBUCKET_PERSONAL_TOKEN`, `$JIRA_URL`…), source the file in that same command:
`set -a; . ~/.kiro/bin/backend-dev/.env; set +a; <command>`. Never print that file or any value from it.
<!-- backend-agent-installer:end -->"""

# Inserted into upstream scripts that read os.environ: the launcher used to export it.
PY_ENV_LOADER = f'''# backend-agent-installer: load the isolated .env the `kiro` launcher used to export.
def _load_isolated_env() -> None:
    import os, pathlib
    path = pathlib.Path.home() / ".kiro" / "bin" / "{AGENT}" / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


_load_isolated_env()
'''


class IsolationError(RuntimeError):
    pass


# ---------- .env ----------

def parse_env(path: Path) -> list[tuple[str | None, str, bool]]:
    """Lines of an env file as (key or None, value-or-raw-line, commented)."""
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = ENV_LINE_RE.match(raw)
        if m:
            out.append((m.group(2), m.group(3).strip().strip("'").strip('"'), bool(m.group(1))))
        else:
            out.append((None, raw, False))
    return out


def read_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return {k: v for k, v, commented in parse_env(path) if k and not commented}


def ask(key: str, default: str) -> str:
    if not sys.stdin.isatty():
        return ""
    hint = "" if SECRET_RE.search(key) else f" [{default}]"
    prompt = f"    {key}{hint}: "
    value = getpass.getpass(prompt) if SECRET_RE.search(key) else input(prompt)
    return value.strip()


def quote(value: str) -> str:
    if value == "" or re.fullmatch(r"[A-Za-z0-9_./:@+,-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def build_env() -> tuple[dict[str, str], list[str]]:
    """Render ~/.kiro/bin/backend-dev/.env from upstream .env.example plus the previous values."""
    template = [
        (k, v, c) for k, v, c in parse_env(UPSTREAM / ".env.example")
        if k not in EXCLUDED_ENV_KEYS and not (k is None and EXCLUDED_ENV_COMMENT_RE.search(v))
    ]
    previous = {k: v for k, v in read_values(ENV_FILE).items() if k not in EXCLUDED_ENV_KEYS}
    values: dict[str, str] = {}
    lines: list[str] = []
    asked = False
    for key, value, commented in template:
        if key is None:
            lines.append(value)
            continue
        if commented and key not in previous:
            lines.append(f"# {key}={quote(value)}")
            continue
        kept = previous.get(key, "")
        if kept and not PLACEHOLDER_RE.search(kept):
            final = kept
        elif PLACEHOLDER_RE.search(value) or SECRET_RE.search(key):
            if not asked:
                print("  Values for the isolated .env (Enter leaves it empty, re-run to fill it):")
                asked = True
            final = ask(key, value) or ("" if PLACEHOLDER_RE.search(value) else value)
        else:
            final = kept or value
        values[key] = final
        lines.append(f"{key}={quote(final)}")
    extra = {k: v for k, v in previous.items() if k not in values}
    if extra:
        lines += ["", "# Kept from the previous install: not in upstream .env.example"]
        lines += [f"{k}={quote(v)}" for k, v in extra.items()]
        values.update(extra)
    BIN.mkdir(parents=True, exist_ok=True)
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)
    return values, sorted(k for k, v in values.items() if not v)


# ---------- text rewrites ----------

def rewrite_text(text: str, where: str) -> str:
    for old, new in ENV_PATH_FIXES + TEXT_FIXES:
        text = text.replace(old, new)
    left = ENV_PATH_LEFT_RE.findall(text)
    # Path.cwd() / ".kiro" / ".env" is a workspace-local fallback upstream keeps; it is harmless.
    if left and not all('".kiro" / ".env"' in m or m == '.kiro" / ".env' for m in left):
        raise IsolationError(f"{where}: a reference to the upstream .env survived: {left}")
    return text


def inject_env_loader(text: str, env_keys: set[str]) -> str:
    """Prepend the loader to a script that reads .env variables from os.environ only."""
    reads = set(re.findall(r"os\.environ(?:\.get)?[\[(]\s*[\"']([A-Z0-9_]+)", text))
    if not reads & env_keys or "_load_isolated_env" in text:
        return text
    lines = text.splitlines(keepends=True)
    at = 0
    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__"):
            at = i
            break
    return "".join(lines[:at]) + PY_ENV_LOADER + "\n" + "".join(lines[at:])


# ---------- agents ----------

def isolate_servers(agent: dict) -> None:
    for name, server in (agent.get("mcpServers") or {}).items():
        args = list(server.get("args") or [])
        env = dict(server.get("env") or {})
        spec = next((a for a in args if not a.startswith("-")), "")
        if server.get("command") == "uvx" and spec.split("@")[0] == "postgres-mcp":
            m = PG_URI_RE.match(env.pop("DATABASE_URI", ""))
            if not m:
                raise IsolationError(f"{agent['name']}/{name}: unexpected DATABASE_URI shape")
            server["command"] = str(BIN / "postgres-mcp.sh")
            server["args"] = [m.group(1), *args]
        elif server.get("command") == "uvx" and spec.split("@")[0] == "mcp-neo4j-cypher":
            envs = set()
            for key in ("NEO4J_URI", "NEO4J_PASSWORD"):
                m = NEO4J_VAR_RE.match(env.pop(key, ""))
                if not m:
                    raise IsolationError(f"{agent['name']}/{name}: unexpected {key} shape")
                envs.add(m.group(1))
            if len(envs) != 1:
                raise IsolationError(f"{agent['name']}/{name}: URI and password name different envs")
            server["command"] = str(BIN / "neo4j-mcp.sh")
            server["args"] = [envs.pop(), *args]
        if env:
            server["env"] = env
        else:
            server.pop("env", None)


def drop_ungranted_servers(agent: dict) -> list[str]:
    """Remove servers no `tools`/`allowedTools` entry covers: they start, hold a connection, and
    the agent can never call them."""
    grants = [t[1:].split("/", 1)[0] for t in (agent.get("tools") or []) + (agent.get("allowedTools") or [])
              if t.startswith("@") and t != "@builtin"]
    if "*" in (agent.get("tools") or []):
        return []
    servers = agent.get("mcpServers") or {}
    dropped = [n for n in servers if not any(fnmatch.fnmatchcase(n, g) for g in grants)]
    for name in dropped:
        del servers[name]
    return dropped


def scope_resources(agent: dict, prompts: set[str]) -> None:
    out = []
    shared = set(SHARED_SKILLS.values())
    for res in agent.get("resources") or []:
        res = re.sub(r"^((?:skill|file)://~/\.kiro/(?:skills|steering))/\*\*", rf"\1/{AGENT}/**", res)
        res = res.replace(f"~/.kiro/steering/{AGENT}/", f"~/.kiro/agent-rules/{AGENT}/")
        m = re.match(r"^(skill|file)://~/\.kiro/(.*)$", res)
        if m:
            rel = m.group(2)
            if not (rel.startswith(tuple(f"{d}/" for d in CONTENT_DIRS.values())) or rel in prompts | shared):
                raise IsolationError(f"{agent['name']}: resource outside the backend-dev namespace: {res}")
            res = f"{m.group(1)}://{KIRO}/{rel}"
        out.append(res)
    # The skills/backend-dev/** glob used to reach upstream's copy of each shared skill.
    if any(r.startswith(f"skill://{KIRO}/skills/{AGENT}/**") for r in out):
        out += [f"skill://{KIRO}/{path}" for path in SHARED_SKILLS.values() if f"skill://{KIRO}/{path}" not in out]
    agent["resources"] = out


def mcp_matches(agent: dict) -> set[str]:
    rules = (agent.get("permissions") or {}).get("rules") or []
    return {m for r in rules if r.get("capability") == "mcp" for m in r.get("match") or []}


def context_text(agent: dict) -> str:
    """The upstream prompt plus every upstream file its resources load."""
    text = agent.get("prompt") or ""
    for res in agent.get("resources") or []:
        m = re.match(r"^(?:skill|file)://~/\.kiro/(.*)$", res)
        if m:
            text += "".join(f.read_text(encoding="utf-8") for f in UPSTREAM.glob(m.group(1)) if f.is_file())
    return text


def wire_subagents(agents: dict[str, dict], texts: dict[str, str]) -> list[str]:
    """Register on each spawning agent the subagents its context names, and their MCP allows.

    Upstream lists no availableAgents: in its own ~/.kiro there is nobody else to spawn.
    A V3 subagent runs under its parent's rules intersected with its own, so a parent
    without the subagent's MCP allows makes that subagent prompt, and fail.
    """
    report = []
    for name, agent in agents.items():
        if "subagent" not in (agent.get("allowedTools") or []):
            continue
        roster = sorted(
            n for n in agents
            if n != name and n not in ORCHESTRATORS
            and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", texts[name])
        )
        agent.setdefault("toolsSettings", {}).setdefault("subagent", {})["availableAgents"] = roster
        needed = set().union(*(mcp_matches(agents[n]) for n in roster)) - mcp_matches(agent)
        if needed and "permissions" in agent:
            rules = agent["permissions"].setdefault("rules", [])
            rule = next((r for r in rules if r.get("capability") == "mcp" and r.get("effect") == "allow"), None)
            if rule is None:
                rule = {"capability": "mcp", "match": [], "effect": "allow"}
                rules.append(rule)
            rule["match"] = sorted(set(rule.get("match") or []) | needed)
            report.append(f"{name}: {len(roster)} subagents, +{len(needed)} MCP allows")
    return report


def verify_agent(agent: dict) -> None:
    text = json.dumps(agent)
    if "${" in text:
        raise IsolationError(f"{agent['name']}: an unresolved ${{VAR}} survived")
    for server in (agent.get("mcpServers") or {}).values():
        for key, value in (server.get("env") or {}).items():
            if SECRET_RE.search(key) and value:
                raise IsolationError(f"{agent['name']}: {key} is still inline")


# ---------- deploy ----------

def collect(env_keys: set[str], source_repos: str) -> dict[str, bytes]:
    """Every file to deploy, keyed by path relative to ~/.kiro."""
    files: dict[str, bytes] = {}
    for top, target in CONTENT_DIRS.items():
        for src in sorted((UPSTREAM / top).rglob("*")):
            if not src.is_file() or "__pycache__" in src.parts:
                continue
            if top == f"skills/{AGENT}" and src.relative_to(UPSTREAM / top).parts[0] in (*SHARED_SKILLS, *EXCLUDED_SKILLS):
                continue
            rel = f"{target}/{src.relative_to(UPSTREAM / top)}"
            data = src.read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                files[rel] = data
                continue
            text = rewrite_text(text, rel)
            if src.suffix == ".py":
                text = inject_env_loader(text, env_keys)
            files[rel] = text.encode("utf-8")
    prompts = set()
    for src in sorted((UPSTREAM / "prompts").glob("*.md")):
        rel = f"prompts/{src.name}"
        prompts.add(rel)
        files[rel] = rewrite_text(src.read_text(encoding="utf-8"), rel).encode("utf-8")

    agents, texts = {}, {}
    for src in sorted((UPSTREAM / "agents").glob("*.json")):
        agent = json.loads(rewrite_text(src.read_text(encoding="utf-8"), src.name))
        texts[agent["name"]] = context_text(json.loads(src.read_text(encoding="utf-8")))
        isolate_servers(agent)
        for name in drop_ungranted_servers(agent):
            print(f"  ✓ {agent['name']}: dropped {name} (declared, never granted)")
        scope_resources(agent, prompts)
        if isinstance(agent.get("prompt"), str) and not agent["prompt"].startswith("file://"):
            agent["prompt"] += PROMPT_NOTE.format(source_repos=source_repos or "not set")
        agents[agent["name"]] = agent
    for line in wire_subagents(agents, texts):
        print(f"  ✓ {line}")
    for name, agent in agents.items():
        verify_agent(agent)
        files[f"agents/{name}.json"] = (json.dumps(agent, indent=2, ensure_ascii=False) + "\n").encode()
    for src in sorted(BIN_TEMPLATES.glob("*.sh")):
        files[f"bin/{AGENT}/{src.name}"] = src.read_bytes()
    return files


def deploy(files: dict[str, bytes]) -> tuple[int, int]:
    previous = set(MANIFEST.read_text().split()) if MANIFEST.is_file() else set()
    foreign = [r for r in files if (KIRO / r).exists() and r not in previous and not r.startswith(f"bin/{AGENT}/")]
    if foreign:
        raise IsolationError("these paths exist and were not installed by this installer:\n    "
                             + "\n    ".join(sorted(foreign)))
    for rel, data in files.items():
        dst = KIRO / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        executable = rel.endswith(".sh") or data.startswith(b"#!")
        os.chmod(dst, 0o755 if executable else 0o644)
    stale = sorted(previous - set(files))
    for rel in stale:
        (KIRO / rel).unlink(missing_ok=True)
    # An excluded skill may also hold runtime files (browser profile, venv) the manifest never saw.
    for name in EXCLUDED_SKILLS:
        shutil.rmtree(KIRO / "skills" / AGENT / name, ignore_errors=True)
    MANIFEST.write_text("\n".join(sorted(files)) + "\n")
    return len(files), len(stale)


def main() -> int:
    try:
        values, empty = build_env()
        print(f"  ✓ {ENV_FILE} (0600, {len(values)} variables)")
        files = collect(set(values), values.get("SOURCE_REPOS_PATH", ""))
        written, removed = deploy(files)
    except IsolationError as exc:
        print(f"\033[1;91m✗ {exc}\033[0m", file=sys.stderr)
        return 1
    print(f"  ✓ {written} files deployed into {KIRO}" + (f", {removed} stale removed" if removed else ""))
    if empty:
        print("\033[0;93m  ⚠ empty in the .env (the skills that need them will fail): "
              + ", ".join(empty) + "\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
