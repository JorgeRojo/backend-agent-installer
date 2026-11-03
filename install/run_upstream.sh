#!/usr/bin/env bash
# run_upstream.sh — Run backend-agent's own install.py inside the temp clone.
# Depends on: ui.sh, helpers.sh, config.sh, sync_upstream.sh (UPSTREAM_DIR).

run_upstream_installer() {
  step "Step 4: Running the upstream install.py in the temp clone"
  dim "  --skip-wrappers: its ~/.local/bin/kiro launcher would export every secret to every session."

  local log="${UPSTREAM_DIR}/.install.log"
  # Its .env seed and git hook stay inside the clone; only `uv tool install` reaches the system.
  if ! (cd "$UPSTREAM_DIR" && python3 install.py --skip-wrappers </dev/null >"$log" 2>&1); then
    sed 's/^/    /' "$log"
    die "the upstream install.py failed."
  fi
  # Its closing banner asks to edit a .env this installer does not use, so only tool lines are shown.
  grep -E '✓|✗|Installing|^!' "$log" | sed 's/^ */    /' || true
  grep -q '✗' "$log" && yellow "  ⚠ some MCP tools failed to install — the agents fall back to uvx on first use."
  green "  ✓ upstream install.py finished"
}
