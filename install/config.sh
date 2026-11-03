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

# Java toolchain (install/toolchain.sh). The repos build with JDK 17; jdtls >= 1.63 needs 21+ to run.
readonly JDK_BUILD="17.0.21.0+9-tem"
readonly MAVEN_VERSION="3.9.16"
readonly JDK_LSP="25.0.5.0+8-tem"
readonly JDTLS_VERSION="1.63.0"
readonly JDTLS_TARBALL="jdt-language-server-1.63.0-202610191322.tar.gz"
readonly JDTLS_SHA256="b1f2abe0b3cccb462cf64fb4a5587c7d09df60cf8be7748b152cbd89d018bdc4"
readonly LOMBOK_VERSION="1.18.48"
readonly CLAUDE_JAVA_LSP_PLUGIN="jdtls-lsp@claude-plugins-official"
