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
# The local Postgres servers are archirelik's: same database, user and postgres-mcp, and every
# extra server is one more connection out of max_connections=100 in every Claude session.
ARCHIRELIK_DB_AGENT = KIRO / "agents" / "sub-archirelik-db.json"
ARCHIRELIK_PG_WRAPPER = KIRO / "bin" / "archirelik" / "postgres-mcp.sh"
# codegraph is archirelik's server too (same pinned npx package as agent-developer's): an own copy
# would be one more Node process in every Claude session. Granted to the agents that read code.
ARCHIRELIK_AGENT = KIRO / "agents" / "archirelik.json"
ARCHIRELIK_ENSURE_CODEGRAPH = KIRO / "bin" / "archirelik" / "ensure-codegraph.sh"
CODEGRAPH_AGENTS = (*ORCHESTRATORS, "code-reviewer", "code-reviewer-critical")
# Installer-owned rules, deployed next to upstream's steering. An agent gets a rule only through
# an explicit resource; the agent-rules glob is expanded to the always-on files.
OVERLAY_RULES = PROJECT_DIR / "overlay" / "agent-rules" / AGENT
RULES_GLOB = f"file://{KIRO}/agent-rules/{AGENT}/**/*.md"
RULE_FOR_SUBAGENTS = {
    "codegraph.md": ("code-reviewer", "code-reviewer-critical"),
    "shell-rtk.md": ("atlassian", "build-verifier", "cache-ops", "code-reviewer",
                     "code-reviewer-critical", "logs-metrics"),
}
# Loaded by every agent of the family. It names the situational rules, which no resource loads.
RULES_INDEX = f"{AGENT}_index.md"
SITUATIONAL_RULES = (
    "infrastructure-architecture.md", "applying-review-comments.md", "rule-change-pr-scope.md",
    "local-toolchain-filesystem.md", "java-toolchain.md",
    "python-style.md", "python-structure.md", "python-testing.md",
)

# Local model choices that win over upstream's.
MODEL_OVERRIDES = {"code-reviewer": "claude-sonnet-5.5"}

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

def archirelik_db_servers() -> dict[str, tuple[str, dict]]:
    """database -> (server name, config) of the archirelik db_* servers."""
    if not (ARCHIRELIK_DB_AGENT.is_file() and os.access(ARCHIRELIK_PG_WRAPPER, os.X_OK)):
        raise IsolationError("archirelik is not installed: its Postgres MCP servers are reused. "
                             "Run the archirelik installer first.")
    out = {}
    for name, conf in (json.loads(ARCHIRELIK_DB_AGENT.read_text(encoding="utf-8")).get("mcpServers") or {}).items():
        if conf.get("command") == str(ARCHIRELIK_PG_WRAPPER) and conf.get("args"):
            out[conf["args"][0]] = (name, conf)
    return out


def rename_mcp_refs(agent: dict, renames: dict[str, list[str]]) -> None:
    """Point `@server[/tool]` grants and `server/tool` permission matches at the new names.
    A glob on the server part (`*-db/execute_sql`) becomes one entry per renamed server it covered."""
    def expand(ref: str) -> list[str]:
        server, sep, tool = ref.partition("/")
        hits = [o for o in renames if fnmatch.fnmatchcase(o, server)]
        if not hits:
            return [ref]
        return list(dict.fromkeys(n + sep + tool for o in hits for n in renames[o]))

    for field in ("tools", "allowedTools"):
        if isinstance(agent.get(field), list):
            agent[field] = list(dict.fromkeys(
                r for t in agent[field]
                for r in (["@" + e for e in expand(t[1:])] if t.startswith("@") and t != "@builtin" else [t])
            ))
    for rule in (agent.get("permissions") or {}).get("rules") or []:
        if rule.get("capability") == "mcp" and rule.get("match"):
            rule["match"] = list(dict.fromkeys(e for m in rule["match"] for e in expand(m)))
    if isinstance(agent.get("toolAliases"), dict):
        agent["toolAliases"] = {
            new: alias for key, alias in agent["toolAliases"].items()
            for new in (["@" + e for e in expand(key[1:])] if key.startswith("@") else [key])
        }


def isolate_servers(agent: dict, pg: dict[str, tuple[str, dict]]) -> dict[str, str]:
    """Rewrite the agent's servers in place. Returns {upstream postgres server -> archirelik name}."""
    renamed: dict[str, str] = {}
    servers: dict[str, dict] = {}
    for name, server in (agent.get("mcpServers") or {}).items():
        args = list(server.get("args") or [])
        env = dict(server.get("env") or {})
        spec = next((a for a in args if not a.startswith("-")), "")
        if server.get("command") == "uvx" and spec.split("@")[0] == "postgres-mcp":
            m = PG_URI_RE.match(env.pop("DATABASE_URI", ""))
            if not m:
                raise IsolationError(f"{agent['name']}/{name}: unexpected DATABASE_URI shape")
            if m.group(1) not in pg:
                raise IsolationError(f"{agent['name']}/{name}: archirelik has no server for {m.group(1)}")
            new, conf = pg[m.group(1)]
            if new in servers:
                raise IsolationError(f"{agent['name']}: two servers point at {m.group(1)}")
            servers[new] = json.loads(json.dumps(conf))
            renamed[name] = new
            continue
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
        servers[name] = server
    if "mcpServers" in agent:
        agent["mcpServers"] = servers
    return renamed


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


def add_codegraph(agent: dict) -> None:
    """Mount archirelik's codegraph server, grant it, and index the repo at session start."""
    conf = (json.loads(ARCHIRELIK_AGENT.read_text(encoding="utf-8")).get("mcpServers") or {}).get("codegraph")
    if not conf or not os.access(ARCHIRELIK_ENSURE_CODEGRAPH, os.X_OK):
        raise IsolationError("archirelik has no codegraph server: re-run the archirelik installer.")
    agent.setdefault("mcpServers", {})["codegraph"] = json.loads(json.dumps(conf))
    for field, grant in (("tools", "@codegraph"), ("allowedTools", "@codegraph/*")):
        if grant not in agent.setdefault(field, []):
            agent[field].append(grant)
    if "permissions" in agent:
        rules = agent["permissions"].setdefault("rules", [])
        rule = next((r for r in rules if r.get("capability") == "mcp" and r.get("effect") == "allow"), None)
        if rule is None:
            rule = {"capability": "mcp", "match": [], "effect": "allow"}
            rules.append(rule)
        rule["match"] = sorted(set(rule.get("match") or []) | {"codegraph/*"})
    if agent["name"] in ORCHESTRATORS:
        hooks = agent.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise IsolationError(f"{agent['name']}: hooks are not in the V2 object form")
        hooks["agentSpawn"] = [
            h for h in hooks.get("agentSpawn") or [] if h.get("command") != str(ARCHIRELIK_ENSURE_CODEGRAPH)
        ] + [{"command": str(ARCHIRELIK_ENSURE_CODEGRAPH), "timeout_ms": 20000}]


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
    for src in sorted(OVERLAY_RULES.glob("*.md")):
        rel = f"agent-rules/{AGENT}/{src.name}"
        if rel in files:
            raise IsolationError(f"{rel}: upstream now ships a rule with this name")
        files[rel] = src.read_bytes()
    index = files.get(f"agent-rules/{AGENT}/{RULES_INDEX}", b"").decode("utf-8")
    named = set(re.findall(r"`([a-z0-9-]+\.md)`", index))
    for rule in SITUATIONAL_RULES:
        if f"agent-rules/{AGENT}/{rule}" not in files:
            raise IsolationError(f"SITUATIONAL_RULES: {rule} is not deployed")
        if rule not in named:
            raise IsolationError(f"{RULES_INDEX} does not name {rule}, so no agent would read it")
    if stray := sorted(named - set(SITUATIONAL_RULES)):
        raise IsolationError(f"{RULES_INDEX} names rules outside SITUATIONAL_RULES: {', '.join(stray)}")
    always_rules = sorted(
        f"file://{KIRO}/{rel}" for rel in files
        if rel.startswith(f"agent-rules/{AGENT}/") and rel.endswith(".md") and rel.rsplit("/", 1)[1] not in SITUATIONAL_RULES
    )
    prompts = set()
    for src in sorted((UPSTREAM / "prompts").glob("*.md")):
        rel = f"prompts/{src.name}"
        prompts.add(rel)
        files[rel] = rewrite_text(src.read_text(encoding="utf-8"), rel).encode("utf-8")

    agents, texts, own = {}, {}, {}
    pg = archirelik_db_servers()
    for src in sorted((UPSTREAM / "agents").glob("*.json")):
        agent = json.loads(rewrite_text(src.read_text(encoding="utf-8"), src.name))
        texts[agent["name"]] = context_text(json.loads(src.read_text(encoding="utf-8")))
        own[agent["name"]] = isolate_servers(agent, pg)
        agents[agent["name"]] = agent
    # An agent without the server (backend-dev allowing its subagents' tools) takes every
    # name it was renamed to: upstream calls two databases `searchkeyword-db`.
    everywhere: dict[str, list[str]] = {}
    for renamed in own.values():
        for old, new in renamed.items():
            everywhere.setdefault(old, [])
            if new not in everywhere[old]:
                everywhere[old].append(new)
    reused = sorted({n for r in own.values() for n in r.values()})
    print(f"  ✓ Postgres: {len(reused)} archirelik servers reused ({', '.join(reused)})")
    for name, agent in agents.items():
        rename_mcp_refs(agent, {**everywhere, **{o: [n] for o, n in own[name].items()}})
        for dropped in drop_ungranted_servers(agent):
            print(f"  ✓ {name}: dropped {dropped} (declared, never granted)")
        if name in CODEGRAPH_AGENTS:
            add_codegraph(agent)
        scope_resources(agent, prompts)
        if RULES_GLOB in agent.get("resources", []):
            i = agent["resources"].index(RULES_GLOB)
            agent["resources"][i:i + 1] = always_rules
        index_res = f"file://{KIRO}/agent-rules/{AGENT}/{RULES_INDEX}"
        if index_res not in agent.setdefault("resources", []):
            agent["resources"].append(index_res)
        for rule, subagents in RULE_FOR_SUBAGENTS.items():
            res = f"file://{KIRO}/agent-rules/{AGENT}/{rule}"
            if name in subagents and res not in agent.setdefault("resources", []):
                agent["resources"].append(res)
        if isinstance(agent.get("prompt"), str) and not agent["prompt"].startswith("file://"):
            agent["prompt"] += PROMPT_NOTE.format(source_repos=source_repos or "not set")
    for line in wire_subagents(agents, texts):
        print(f"  ✓ {line}")
    for name, model in MODEL_OVERRIDES.items():
        if name not in agents:
            raise IsolationError(f"MODEL_OVERRIDES: upstream no longer ships {name}")
        if agents[name].get("model") != model:
            print(f"  ✓ {name}: model {agents[name].get('model')} -> {model}")
            agents[name]["model"] = model
    for name, agent in agents.items():
        verify_agent(agent)
        files[f"agents/{name}.json"] = (json.dumps(agent, indent=2, ensure_ascii=False) + "\n").encode()
    if everywhere:
        old_ref = re.compile(r"(?:@|mcp__)(?:" + "|".join(map(re.escape, sorted(everywhere, key=len, reverse=True)))
                             + r")(?:/|__)")
        if left := sorted(rel for rel, data in files.items() if old_ref.search(data.decode("utf-8", "ignore"))):
            raise IsolationError("a replaced Postgres server is still named in: " + ", ".join(left))
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
