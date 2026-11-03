#!/usr/bin/env bash
set -euo pipefail

# backend-agent-installer — installs the team backend-agent into ~/.kiro with an isolated
# environment, without making ~/.kiro a clone of it. Steps:
#   1 prerequisites · 2 clone backend-agent@master into a temp dir · 3 compatibility check
#   4 upstream install.py inside the clone · 5 isolation layer · 6 validation
#   7 Claude Code / Antigravity sync · 8 MCP mount check

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly LIB_DIR="${SCRIPT_DIR}/install"

ACCEPT_UPSTREAM=false
SKIP_CLIENTS=false
for _arg in "$@"; do
  case "$_arg" in
    --accept-upstream) ACCEPT_UPSTREAM=true ;;
    --no-sync) SKIP_CLIENTS=true ;;
    -h|--help)
      cat <<'EOF'
Usage: install.sh [--accept-upstream] [--no-sync]

  --accept-upstream   Proceed when upstream install.py changed, then re-pin upstream.lock.
  --no-sync           Do not render the agents into Claude Code and Antigravity.

Values already in ~/.kiro/bin/backend-dev/.env are kept; only empty or placeholder
values are asked for.
EOF
      exit 0
      ;;
    *) printf '\033[1;91m✗ Unknown option: %s\033[0m\n' "$_arg" >&2; exit 1 ;;
  esac
done
unset _arg
readonly ACCEPT_UPSTREAM SKIP_CLIENTS

# shellcheck source=/dev/null
for _lib in ui helpers config prerequisites sync_upstream check_compat run_upstream sync_clients; do
  source "${LIB_DIR}/${_lib}.sh"
done
unset _lib

cleanup_upstream() {
  local status=$?
  [[ -d "${UPSTREAM_DIR:-}" ]] || return 0
  if ((status == 0)); then
    rm -rf "$UPSTREAM_DIR"
  else
    echo ""
    yellow "  ▸ Upstream clone kept for inspection: ${UPSTREAM_DIR}"
  fi
}
trap cleanup_upstream EXIT

validate_agents() {
  step "Step 6: Validating the deployed agents"
  local f name failed=0
  while read -r f; do
    [[ "$f" == agents/*.json ]] || continue
    name="${f#agents/}"
    kiro-cli agent validate --path "${KIRO_DIR}/${f}" </dev/null >/dev/null 2>&1 \
      || { red "invalid: ${name}"; failed=1; }
  done <"${BIN_DIR}/.manifest"
  ((failed == 0)) || die "kiro-cli rejected one or more agents."
  green "  ✓ every agent JSON validates"
}

verify_mcp_mounts() {
  step "Step 8: Verifying the MCP servers mount"
  local agents
  agents="$(sed -n 's#^agents/\(.*\)\.json$#\1#p' "${BIN_DIR}/.manifest" \
    | while read -r a; do grep -q '"mcpServers"' "${KIRO_DIR}/agents/${a}.json" && echo "$a"; done)"
  # shellcheck disable=SC2086  # one agent name per word
  if python3 "${LIB_DIR}/mcp_mount_check.py" --source kiro $agents; then
    green "  ✓ every declared MCP server handed shake and listed tools"
  else
    yellow "  ⚠ some servers did not start. Local Postgres and Neo4j must be running, PRE/PRO need the VPN."
  fi
}

main() {
  bold "backend-agent-installer"
  [[ -d "$KIRO_DIR" ]] || die "${KIRO_DIR} not found — install kiro-cli and run it once first."

  check_prerequisites
  sync_upstream
  check_upstream_compat
  run_upstream_installer

  step "Step 5: Isolating the environment"
  export UPSTREAM_DIR KIRO_DIR
  python3 "${SCRIPT_DIR}/isolate/isolate.py" || die "the isolation layer failed."
  # Upstream ships the agents already universal; a launch-time upgrade would rewrite them.
  kiro-cli settings chat.enableAutoAgentUpgrade false </dev/null >/dev/null 2>&1 \
    || yellow "  ⚠ could not set chat.enableAutoAgentUpgrade false"
  [[ "$(stat -c '%a' "${BIN_DIR}/.env")" == 600 ]] || die "${BIN_DIR}/.env is not mode 600."

  validate_agents
  update_upstream_lock
  if [[ "$SKIP_CLIENTS" == true ]]; then
    dim "  --no-sync: Claude Code and Antigravity left untouched"
  else
    sync_clients
  fi
  verify_mcp_mounts

  step "Installation complete"
  green "  ✓ Secrets: ${BIN_DIR}/.env (600) — no agent JSON holds one"
  cyan  "  ▸ Run:       kiro-cli chat --agent ${AGENT}   (PRE checks: --agent backend-pre-verifier)"
  dim   "  ▸ Uninstall: ${SCRIPT_DIR}/uninstall.sh"
}

main "$@"
