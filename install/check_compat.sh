#!/usr/bin/env bash
# check_compat.sh — Verify the freshly cloned backend-agent still matches the
# contract the isolation layer was built against.
# Depends on: ui.sh, helpers.sh, config.sh, sync_upstream.sh (UPSTREAM_DIR).
#
# The commit moving forward is expected and harmless — that is new agent content.
# What matters is whether upstream install.py changed: run_upstream.sh depends on
# its flags and on it writing nothing outside the clone but `uv tool` installs. upstream.lock fingerprints exactly
# those files; COMPAT.md explains what to do when one of them drifts.

check_upstream_compat() {
  step "Step 3: Checking upstream installer compatibility"

  [[ -f "$UPSTREAM_LOCK" ]] || die "missing ${UPSTREAM_LOCK} — cannot verify compatibility."

  local head
  head="$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null || true)"
  [[ -n "$head" ]] || die "${UPSTREAM_DIR} is not a git clone — cannot verify compatibility."

  # Paths go in as arguments: a `VAR=… cmd` prefix fails on these, they are
  # readonly in config.sh.
  local drift
  drift="$(python3 - "$UPSTREAM_DIR" "$UPSTREAM_LOCK" <<'PY'
import hashlib, json, sys
from pathlib import Path

upstream = Path(sys.argv[1])
lock = json.loads(Path(sys.argv[2]).read_text())

for path, expected in lock["contract"].items():
    target = upstream / path
    if not target.exists():
        print(f"MISSING  {path}")
        continue
    actual = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    if actual != expected:
        print(f"CHANGED  {path}  ({expected} -> {actual})")
PY
)" || die "compatibility check failed to run."

  local pinned
  pinned="$(python3 -c \
    'import json, sys; print(json.load(open(sys.argv[1]))["commit"])' "$UPSTREAM_LOCK")"

  if [[ "$head" == "$pinned" ]]; then
    green "  ✓ master is at the validated commit (${head:0:12})"
  else
    dim "  master moved: ${pinned:0:12} -> ${head:0:12} (new agent content is expected)"
  fi

  if [[ -z "$drift" ]]; then
    green "  ✓ upstream installer unchanged — the isolation layer is compatible"
    return
  fi

  echo ""
  red "The upstream installer changed. The isolation layer may be incompatible:"
  echo "$drift" | sed 's/^/    /'
  echo ""
  yellow "  ▸ Investigation and update plan: ${SCRIPT_DIR}/COMPAT.md"
  yellow "  ▸ The clone is kept on abort — diff it with:"
  dim   "      git -C ${UPSTREAM_DIR} diff ${pinned}..HEAD -- install.py"
  echo ""
  yellow "  Installing anyway may produce an agent with credentials left in its JSON."
  echo ""
  if [[ "${ACCEPT_UPSTREAM:-false}" == true ]]; then
    yellow "  --accept-upstream given: continuing and re-pinning after the install."
  elif ! confirm "  Continue with the install?"; then
    die "Aborted. Follow COMPAT.md, then re-run with --accept-upstream."
  fi
}

# Re-pin upstream.lock to the current clone. Only meaningful after a successful,
# manually verified install (--accept-upstream).
update_upstream_lock() {
  [[ "${ACCEPT_UPSTREAM:-false}" == true ]] || return 0
  step "Re-pinning ${UPSTREAM_LOCK##*/}"
  python3 - "$UPSTREAM_DIR" "$UPSTREAM_LOCK" <<'PY'
import hashlib, json, subprocess, sys
from datetime import date
from pathlib import Path

upstream = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
lock = json.loads(lock_path.read_text())


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(upstream), *args], text=True).strip()


lock["commit"] = git("rev-parse", "HEAD")
lock["commit_date"] = git("log", "-1", "--format=%cI")
lock["commit_subject"] = git("log", "-1", "--format=%s")
lock["validated_at"] = date.today().isoformat()
lock["contract"] = {
    path: hashlib.sha256((upstream / path).read_bytes()).hexdigest()[:16]
    for path in lock["contract"]
    if (upstream / path).exists()
}
lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
print(f"  pinned to {lock['commit'][:12]} ({lock['commit_date']})")
PY
  green "  ✓ ${UPSTREAM_LOCK##*/} updated — commit the change"
}
