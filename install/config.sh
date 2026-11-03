#!/usr/bin/env bash
# config.sh — Constants only. Requires SCRIPT_DIR from the entrypoint.
# Side-effect free so uninstall.sh can source it too.

readonly AGENT="backend-dev"
readonly KIRO_DIR="${HOME}/.kiro"
readonly BIN_DIR="${KIRO_DIR}/bin/${AGENT}"

readonly UPSTREAM_REPO="ssh://git@bitbucket.rdpnts.com:7999/aiagents/backend-agent.git"
readonly UPSTREAM_BRANCH="master"
# Throwaway clone created by sync_upstream.sh; install.sh removes it on success.
UPSTREAM_DIR=""
readonly UPSTREAM_LOCK="${SCRIPT_DIR}/upstream.lock"

readonly MIN_PYTHON_VERSION="3.11.0"
# Upstream agents ship already universal (V2 fields + permissions); validate needs a 2.35+ CLI.
readonly MIN_KIRO_CLI_VERSION="2.35.1"
# Same floor as agent-developer and archirelik (their install/versions.json).
readonly MIN_RTK_VERSION="0.49.0"
