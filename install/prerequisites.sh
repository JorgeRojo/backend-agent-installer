#!/usr/bin/env bash
# prerequisites.sh — What has to exist before the installer can run.
# Depends on: ui.sh, helpers.sh, config.sh.

check_prerequisites() {
  step "Step 1: Checking prerequisites"

  [[ ":$PATH:" == *":${HOME}/.local/bin:"* ]] || export PATH="${HOME}/.local/bin:$PATH"

  local -A required=(
    [python3]="runs the upstream installer and the isolation layer"
    [git]="clones backend-agent"
    [uv]="installs and runs the MCP servers (uv tool / uvx)"
    [kiro-cli]="validates the deployed agents"
  )
  local missing=() cmd
  for cmd in "${!required[@]}"; do
    command_exists "$cmd" || missing+=("${cmd} (${required[$cmd]})")
  done
  if ((${#missing[@]})); then
    red "Missing:"
    printf '    - %s\n' "${missing[@]}"
    die "Install the above and re-run."
  fi

  require_version python3 "$MIN_PYTHON_VERSION" "$(python3 --version 2>&1)"
  require_version kiro-cli "$MIN_KIRO_CLI_VERSION" "$(kiro-cli --version 2>/dev/null </dev/null)"

  if [[ -n "${KIRO_HOME:-}" && "${KIRO_HOME%/}" != "$KIRO_DIR" ]]; then
    die "KIRO_HOME=${KIRO_HOME} is not ${KIRO_DIR}. Only ~/.kiro is supported: unset KIRO_HOME and re-run."
  fi
  # The upstream README installs the repo AS ~/.kiro. That layout cannot coexist with this one.
  if [[ -d "${KIRO_DIR}/.git" ]] && git -C "$KIRO_DIR" remote -v 2>/dev/null | grep -q 'backend-agent\|backend-kiro'; then
    die "${KIRO_DIR} is a clone of backend-agent. Move it aside before installing the isolated layout."
  fi

  command_exists redpoints || yellow "  ⚠ redpoints CLI not found — PRO/PRE psql and cache-ops need it."
  green "✓ Prerequisites satisfied"
}

# require_version <label> <minimum> <version output>
require_version() {
  local label="$1" minimum="$2" found
  found="$(extract_version "$3")"
  [[ -n "$found" ]] || die "${label} not found (need >= ${minimum})."
  version_ge "$found" "$minimum" || die "${label} ${found} < ${minimum} — upgrade it and re-run."
  green "  ✓ ${label} ${found} (>= ${minimum})"
}
