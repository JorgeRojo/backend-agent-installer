#!/usr/bin/env bash
# helpers.sh — Generic helper functions.
# Depends on ui.sh (die uses red). Sourced by install.sh.
# shellcheck disable=SC2155  # Allow declare and assign on same line.

command_exists() { command -v "$1" &>/dev/null; }

# version_ge <have> <min> → 0 if have >= min (semantic version compare)
version_ge() {
  [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

extract_version() {
  grep -oE '[0-9]+(\.[0-9]+)+' <<<"$1" | head -n1
}

die() {
  red "ERROR: $*" >&2
  exit 1
}

confirm() {
  local prompt="${1:-Continue?}"
  printf '%s [y/N] ' "$prompt"
  read -r answer
  [[ "${answer,,}" == "y" ]]
}


