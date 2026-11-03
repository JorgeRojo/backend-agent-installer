#!/usr/bin/env bash
# sync_clients.sh — Render the deployed agents into Claude Code and Antigravity (agy).
# Depends on: ui.sh, helpers.sh, config.sh.
# Both renderers are the user's own tools (~/.claude/bin, ~/.gemini/bin) and must already
# list backend-dev and backend-pre-verifier as orchestrators; a missing one is skipped.

readonly KIRO_SYNC="${HOME}/.claude/bin/kiro-sync.py"
readonly RP_AGENT="${HOME}/.claude/bin/rp-agent"
readonly KIRO_TO_AGY="${HOME}/.gemini/bin/kiro-to-agy.py"
readonly AGY_CONFIG="${HOME}/.gemini/config/config.json"
readonly SYNC_FAMILIES=("$AGENT" backend-pre-verifier)

sync_clients() {
  step "Step 7: Syncing Claude Code and Antigravity"
  sync_claude
  sync_agy
}

sync_claude() {
  if [[ ! -x "$KIRO_SYNC" ]]; then
    dim "  ~/.claude/bin/kiro-sync.py not found — Claude Code skipped"
    return 0
  fi
  grep -q "\"${AGENT}\"" "$KIRO_SYNC" || die "kiro-sync.py does not list ${AGENT} in ORCHESTRATORS."
  python3 "$KIRO_SYNC" --apply >"${UPSTREAM_DIR}/.kiro-sync.log" 2>&1 \
    || { sed 's/^/    /' "${UPSTREAM_DIR}/.kiro-sync.log"; die "kiro-sync failed."; }
  grep -E '^  (create|MISSING)' "${UPSTREAM_DIR}/.kiro-sync.log" | sed 's/^ */    /'
  local name
  for name in "${SYNC_FAMILIES[@]}"; do
    [[ -f "${HOME}/.claude/agents/${name}.md" ]] || die "kiro-sync did not render ${name}.md."
    # Same thin wrapper as the other families: rp-agent runs claude from the project root.
    if [[ -x "$RP_AGENT" && ! -e "${HOME}/.claude/bin/${name}" ]]; then
      printf '#!/usr/bin/env bash\n# %s — thin wrapper around rp-agent.\nexec env RP_AGENT=%s "$HOME/.claude/bin/rp-agent" "$@"\n' \
        "$name" "$name" >"${HOME}/.claude/bin/${name}"
      chmod 755 "${HOME}/.claude/bin/${name}"
    fi
  done
  green "  ✓ Claude Code: ~/.claude/agents/{${AGENT},backend-pre-verifier}.md"
}

sync_agy() {
  if [[ ! -x "$KIRO_TO_AGY" ]]; then
    dim "  ~/.gemini/bin/kiro-to-agy.py not found — Antigravity skipped"
    return 0
  fi
  local family
  for family in "${SYNC_FAMILIES[@]}"; do
    grep -q "\"${family}\"" "$KIRO_TO_AGY" || die "kiro-to-agy.py does not list ${family} in ORCHESTRATORS."
    python3 "$KIRO_TO_AGY" --apply --only "$family" >"${UPSTREAM_DIR}/.kiro-to-agy.log" 2>&1 \
      || { sed 's/^/    /' "${UPSTREAM_DIR}/.kiro-to-agy.log"; die "kiro-to-agy failed for ${family}."; }
    if command_exists agy; then
      # agy enables a plugin with no config.json entry, and enabled plugins share one rule set.
      python3 -c 'import json,sys; sys.exit(sys.argv[2] in json.load(open(sys.argv[1])).get("plugins",{}))' \
        "$AGY_CONFIG" "$family" 2>/dev/null \
        && { timeout 30 agy plugin disable "$family" </dev/null >/dev/null 2>&1 || true; }
      timeout 60 agy plugin validate "${HOME}/.gemini/config/plugins/${family}" </dev/null >/dev/null 2>&1 \
        || yellow "  ⚠ agy plugin validate reports problems in ${family}"
    fi
  done
  green "  ✓ Antigravity: plugins ${SYNC_FAMILIES[*]} (enable one with: agy plugin enable <name>)"
}
