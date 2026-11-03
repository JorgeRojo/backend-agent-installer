#!/usr/bin/env bash
# _common.sh — sourced by every backend-dev wrapper: loads the isolated .env next to it.
_ISOLATED_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.env"
set -a
# shellcheck source=/dev/null
source "$_ISOLATED_ENV"
set +a
export PATH="$HOME/.local/bin:$PATH"
