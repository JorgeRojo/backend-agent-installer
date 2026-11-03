#!/usr/bin/env bash
set -euo pipefail

# Removes every file install.sh deployed into ~/.kiro (listed in bin/backend-dev/.manifest).
# The Claude Code and agy copies are pruned by their own renderers on the next sync.

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
for _lib in ui helpers config; do
  source "${SCRIPT_DIR}/install/${_lib}.sh"
done
unset _lib

main() {
  bold "backend-agent-installer — uninstall"
  local manifest="${BIN_DIR}/.manifest"
  [[ -f "$manifest" ]] || die "${manifest} not found — nothing installed by this installer."

  yellow "Removes $(wc -l <"$manifest") files listed in ${manifest}, and ${BIN_DIR}/ with your .env."
  confirm "Continue?" || { echo "Aborted."; exit 0; }

  local rel
  while read -r rel; do
    [[ -n "$rel" ]] && rm -f "${KIRO_DIR}/${rel}"
  done <"$manifest"
  rm -rf "$BIN_DIR"
  find "${KIRO_DIR}/skills/${AGENT}" "${KIRO_DIR}/agent-rules/${AGENT}" -depth -type d -empty -delete 2>/dev/null || true
  green "✓ Removed"
  dim "  Run ~/.claude/bin/kiro-sync.py --apply and ~/.gemini/bin/kiro-to-agy.py --apply after"
  dim "  removing backend-dev and backend-pre-verifier from their ORCHESTRATORS."
  dim "  uv tools are kept: uv tool uninstall mcp-neo4j-cypher (postgres-mcp is archirelik's)"
  dim "  ~/.kiro/skills/kevint is kept (shared with archirelik): kevint skill uninstall --path ~/.kiro/skills --yes"
  dim "  The Java toolchain is kept: ~/.local/bin/{mvn,jdtls}, ~/.local/share/jdtls, ~/.cache/jdtls,"
  dim "  claude plugin uninstall jdtls-lsp@claude-plugins-official"
}

main "$@"
