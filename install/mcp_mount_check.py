#!/usr/bin/env python3
"""Probe every MCP server an agent declares and report which ones actually mount.

Reads agent definitions from ~/.claude/agents/<name>.md (YAML frontmatter) or
~/.kiro/agents/<name>.json, spawns each non-disabled server over stdio and drives
initialize + tools/list. A server that fails here is absent from the agent's toolset
for the whole life of a session: Claude Code does not retry a server that failed to
connect at startup.

Exit status is 1 when any server fails to hand shake or returns no tools.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
CLAUDE_AGENTS = HOME / ".claude" / "agents"
KIRO_AGENTS = HOME / ".kiro" / "agents"


def parse_claude_agent(path: Path) -> tuple[set[str] | None, list[dict]]:
    """Return (server names granted in `tools`, server configs) from a rendered agent.

    A None grant set means every tool is granted, so the grant cross-check is skipped.
    """
    import yaml

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: no frontmatter")
    fm = yaml.safe_load(text.split("---", 2)[1])
    tools = [t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()]
    granted = None if "*" in tools else {
        t[len("mcp__"):].split("__", 1)[0] for t in tools if t.startswith("mcp__")
    }
    servers = []
    raw = fm.get("mcpServers") or []
    # kiro-sync renders mcpServers as a list of single-key maps.
    entries = raw if isinstance(raw, list) else [{k: v} for k, v in raw.items()]
    for item in entries:
        for name, conf in item.items():
            servers.append({"name": name, **(conf or {})})
    return granted, servers


def parse_kiro_agent(path: Path) -> tuple[set[str] | None, list[dict]]:
    """Same contract as parse_claude_agent, for a kiro agent JSON.

    kiro grants MCP tools as `@<server>/<tool>` entries in allowedTools; `<server>` may be a
    glob (`@*-db/execute_sql`), so the names returned here are patterns.
    """
    cfg = json.loads(path.read_text(encoding="utf-8"))
    granted = None if "*" in (cfg.get("tools") or []) else {
        t[1:].split("/", 1)[0] for t in (cfg.get("allowedTools") or []) if t.startswith("@")
    }
    servers = [{"name": n, **(c or {})} for n, c in (cfg.get("mcpServers") or {}).items()]
    return granted, servers


def _pump(stream, out: "queue.Queue[str | None]") -> None:
    try:
        for line in stream:
            out.put(line)
    except (ValueError, OSError):
        pass
    out.put(None)


def _drain(stream, sink) -> None:
    try:
        sink(stream.read())
    except (ValueError, OSError):
        pass


def probe(server: dict, timeout: float) -> dict:
    """Drive one stdio MCP server through initialize + tools/list."""
    name = server["name"]
    command = server.get("command")
    if not command:
        return {"server": name, "status": "NO_COMMAND", "tools": 0, "detail": ""}

    env = dict(os.environ)
    env.update({k: str(v) for k, v in (server.get("env") or {}).items()})
    try:
        proc = subprocess.Popen(
            [command, *[str(a) for a in server.get("args") or []]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, bufsize=1, start_new_session=True,
        )
    except (FileNotFoundError, PermissionError, NotADirectoryError) as exc:
        return {"server": name, "status": "SPAWN_FAIL", "tools": 0, "detail": str(exc)}

    # Both pipes are drained by threads: a server that never answers must hit the
    # deadline instead of blocking the probe forever on readline().
    stderr: list[str] = []
    lines: queue.Queue[str | None] = queue.Queue()
    err_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr.append), daemon=True)
    err_thread.start()
    threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True).start()

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def done(status: str, count: int = 0, detail: str = "") -> dict:
        # Kill the whole process group: a wrapper script's `exec`ed child would otherwise
        # survive holding the pipes open, and the reader threads would never see EOF.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        err_thread.join(2)
        # stdout and stderr stay open: closing a stream another thread is blocked in
        # read() on deadlocks. The daemon reader threads die with the interpreter.
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        proc.wait()
        return {"server": name, "status": status, "tools": count,
                "detail": detail or "".join(s for s in stderr if s).strip()[-400:]}

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "mcp-mount-check", "version": "1"}}})
    except (BrokenPipeError, OSError):
        return done("SPAWN_FAIL")

    deadline = time.time() + timeout
    info, listed, phase = None, None, "init"
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:  # stdout closed: the server died
            break
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 1 and phase == "init":
            if "error" in msg:
                return done("INIT_ERROR", detail=json.dumps(msg["error"])[:400])
            info, phase = msg, "tools"
            try:
                send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            except (BrokenPipeError, OSError):
                return done("NO_TOOLS_REPLY")
        elif msg.get("id") == 2:
            listed = msg
            break

    if info is None:
        return done("NO_HANDSHAKE")
    if listed is None:
        return done("NO_TOOLS_REPLY")
    if "error" in listed:
        return done("TOOLS_ERROR", detail=json.dumps(listed["error"])[:400])

    count = len(listed["result"].get("tools", []))
    srv = info["result"].get("serverInfo", {})
    status = "OK" if count else "EMPTY_TOOLS"
    return done(status, count, f"{srv.get('name', '?')} {srv.get('version', '?')}")


def check_agent(path: Path, kind: str, timeout: float, jobs: int, skip: tuple[str, ...] = ()) -> int:
    granted, servers = (parse_kiro_agent if kind == "kiro" else parse_claude_agent)(path)
    enabled = [s for s in servers if not s.get("disabled")]
    skipped = [s["name"] for s in servers if s.get("disabled")]

    print(f"\n{path.name}  ({len(enabled)} enabled server(s), {len(skipped)} disabled)")
    for s in [s for s in enabled if any(fnmatch.fnmatchcase(s["name"], g) for g in skip)]:
        print(f"  SKIP  {s['name']:<28} not probed (--skip)")
        enabled.remove(s)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(lambda s: probe(s, timeout), enabled))

    failures = 0
    for r in sorted(results, key=lambda r: r["server"]):
        if r["status"] == "OK":
            print(f"  OK    {r['server']:<28} {r['tools']:>3} tools  ({r['detail']})")
        else:
            failures += 1
            print(f"  FAIL  {r['server']:<28} {r['status']}: {r['detail']}")

    if granted is not None:
        declared = {s["name"] for s in servers}
        covered = {d for d in declared if any(fnmatch.fnmatchcase(d, g) for g in granted)}
        dangling = {g for g in granted if not any(fnmatch.fnmatchcase(d, g) for d in declared)}
        for name in sorted(dangling):
            failures += 1
            print(f"  FAIL  {name:<28} GRANTED_NOT_DECLARED: the tool grant names it "
                  f"but no server declares it")
        for name in sorted(declared - covered):
            print(f"  WARN  {name:<28} DECLARED_NOT_GRANTED: no tool grant references it")

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify every declared MCP server mounts")
    ap.add_argument("agents", nargs="*", help="agent names (default: all)")
    ap.add_argument("--source", choices=("claude", "kiro"), default="claude")
    ap.add_argument("--timeout", type=float, default=90.0, help="seconds per server")
    ap.add_argument("--jobs", type=int, default=4, help="concurrent probes")
    ap.add_argument("--skip", action="append", default=[], metavar="GLOB",
                    help="server names not to probe (repeatable)")
    args = ap.parse_args()

    root, suffix = (KIRO_AGENTS, ".json") if args.source == "kiro" else (CLAUDE_AGENTS, ".md")
    if not root.is_dir():
        print(f"error: {root} not found", file=sys.stderr)
        return 1

    if args.agents:
        paths = [root / f"{a}{suffix}" for a in args.agents]
        for p in paths:
            if not p.is_file():
                print(f"error: {p} not found", file=sys.stderr)
                return 1
    else:
        paths = sorted(root.glob(f"*{suffix}"))

    total = 0
    for p in paths:
        try:
            total += check_agent(p, args.source, args.timeout, args.jobs, tuple(args.skip))
        except Exception as exc:  # a malformed definition is itself a failure
            total += 1
            print(f"\n{p.name}\n  FAIL  <parse>                     {type(exc).__name__}: {exc}")

    print(f"\n{len(paths)} agent(s) checked, {total} failure(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
