#!/usr/bin/env bash
# kevint_skill.sh — Install or update the kevint skill shared with archirelik.
# Depends on: ui.sh, helpers.sh, config.sh.

install_kevint_skill() {
  local dir="${KIRO_DIR}/skills"
  if ! command_exists kevint; then
    yellow "  ⚠ kevint CLI not found — ${dir}/kevint is not installed or updated; the agents load it from there."
    return 0
  fi
  # --path keeps it non-interactive (without it the CLI asks for the target); a re-run replaces the copy.
  if kevint skill install -p "$dir" </dev/null >/dev/null 2>&1; then
    green "  ✓ kevint skill (${dir}/kevint)"
  else
    yellow "  ⚠ kevint skill could not be installed. By hand: kevint skill install -p ${dir}"
  fi
}
