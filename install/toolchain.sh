#!/usr/bin/env bash
# toolchain.sh — Java toolchain and language server the agents use, plus the dev-tools check.
# Depends on: ui.sh, helpers.sh, config.sh.

readonly SDKMAN_ROOT="${SDKMAN_DIR:-${HOME}/.sdkman}"
readonly JDK17_HOME="${SDKMAN_ROOT}/candidates/java/${JDK_BUILD}"
readonly JDK_LSP_HOME="${SDKMAN_ROOT}/candidates/java/${JDK_LSP}"
readonly MAVEN_HOME="${SDKMAN_ROOT}/candidates/maven/${MAVEN_VERSION}"
readonly JDTLS_ROOT="${HOME}/.local/share/jdtls"
readonly JDTLS_HOME="${JDTLS_ROOT}/${JDTLS_VERSION}"
readonly LOMBOK_JAR="${JDTLS_ROOT}/lombok-${LOMBOK_VERSION}.jar"
readonly LOCAL_BIN="${HOME}/.local/bin"
# First line of every file this step renders: an existing file without it is the user's, never overwritten.
readonly RENDER_MARK="backend-agent-installer:toolchain"

install_toolchain() {
  step "Step 9: Java toolchain and language server"
  [[ -s "${SDKMAN_ROOT}/bin/sdkman-init.sh" ]] \
    || die "sdkman not found. Install it (https://sdkman.io/install) and re-run."
  sdk_install java "$JDK_BUILD"
  sdk_install maven "$MAVEN_VERSION"
  sdk_install java "$JDK_LSP"
  # sdkman_auto_answer=true makes every install the default: the default must stay the build JDK.
  sdk_run default java "$JDK_BUILD" >/dev/null 2>&1
  install_jdtls
  render "${SCRIPT_DIR}/toolchain/mvn" "${LOCAL_BIN}/mvn"
  render "${SCRIPT_DIR}/toolchain/jdtls" "${LOCAL_BIN}/jdtls"
  install_claude_lsp_plugin
  ignore_lsp_files
  green "  ✓ JDK ${JDK_BUILD} (default), Maven ${MAVEN_VERSION}, jdtls ${JDTLS_VERSION} on JDK ${JDK_LSP}"
}

# jdtls writes .factorypath next to every Maven module and kiro's /code init writes
# .kiro/settings/lsp.json at the repo root; git's default global excludes file hides both.
readonly GIT_IGNORE="${XDG_CONFIG_HOME:-${HOME}/.config}/git/ignore"
readonly LSP_IGNORES=(".factorypath" ".kiro/settings/lsp.json")

ignore_lsp_files() {
  if git config --global --get core.excludesFile >/dev/null; then
    yellow "  ⚠ core.excludesFile is set: add ${LSP_IGNORES[*]} to it by hand"
    return 0
  fi
  mkdir -p "$(dirname "$GIT_IGNORE")"
  touch "$GIT_IGNORE"
  local pattern
  for pattern in "${LSP_IGNORES[@]}"; do
    grep -qxF "$pattern" "$GIT_IGNORE" || echo "$pattern" >>"$GIT_IGNORE"
  done
}

sdk_run() {
  # shellcheck disable=SC2016  # expanded by the inner bash
  SDKMAN_DIR="$SDKMAN_ROOT" bash -c 'source "$SDKMAN_DIR/bin/sdkman-init.sh" && sdk "$@"' sdk "$@" </dev/null
}

sdk_install() {
  local candidate="$1" version="$2"
  [[ -d "${SDKMAN_ROOT}/candidates/${candidate}/${version}" ]] && return 0
  dim "  installing ${candidate} ${version} with sdkman"
  sdk_run install "$candidate" "$version" >/dev/null || die "sdk install ${candidate} ${version} failed."
}

install_jdtls() {
  mkdir -p "$JDTLS_ROOT"
  if [[ ! -d "${JDTLS_HOME}/plugins" ]]; then
    local tmp
    tmp="$(mktemp -d)"
    dim "  downloading jdtls ${JDTLS_VERSION}"
    curl -fsSL -o "${tmp}/${JDTLS_TARBALL}" \
      "https://download.eclipse.org/jdtls/milestones/${JDTLS_VERSION}/${JDTLS_TARBALL}" \
      || die "jdtls download failed."
    echo "${JDTLS_SHA256}  ${tmp}/${JDTLS_TARBALL}" | sha256sum -c --quiet - || die "jdtls checksum mismatch."
    mkdir -p "$JDTLS_HOME"
    tar -xzf "${tmp}/${JDTLS_TARBALL}" -C "$JDTLS_HOME"
    rm -rf "$tmp"
  fi
  if [[ ! -s "$LOMBOK_JAR" ]]; then
    local url="https://repo1.maven.org/maven2/org/projectlombok/lombok/${LOMBOK_VERSION}/lombok-${LOMBOK_VERSION}.jar"
    curl -fsSL -o "$LOMBOK_JAR" "$url" || die "lombok download failed."
    echo "$(curl -fsSL "${url}.sha1")  ${LOMBOK_JAR}" | sha1sum -c --quiet - \
      || { rm -f "$LOMBOK_JAR"; die "lombok checksum mismatch."; }
  fi
}

# render <template> <target>: fills the @VAR@ placeholders; refuses to replace a file it did not write.
render() {
  local src="$1" dst="$2"
  if [[ -e "$dst" ]] && ! sed -n 2p "$dst" | grep -q "$RENDER_MARK"; then
    yellow "  ⚠ ${dst} exists and was not written by this installer — left as is"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  sed -e "1a # ${RENDER_MARK}" \
    -e "s#@JDK17@#${JDK17_HOME}#g" -e "s#@JDK_RUNTIME@#${JDK_LSP_HOME}#g" \
    -e "s#@MAVEN_HOME@#${MAVEN_HOME}#g" -e "s#@JDTLS_HOME@#${JDTLS_HOME}#g" \
    -e "s#@LOMBOK_JAR@#${LOMBOK_JAR}#g" "$src" >"$dst"
  chmod 755 "$dst"
}

install_claude_lsp_plugin() {
  if ! command_exists claude; then
    dim "  claude not found — ${CLAUDE_JAVA_LSP_PLUGIN} skipped"
    return 0
  fi
  if claude_plugin_installed "$CLAUDE_JAVA_LSP_PLUGIN"; then
    return 0
  fi
  timeout 120 claude plugin install "$CLAUDE_JAVA_LSP_PLUGIN" --scope user </dev/null >/dev/null 2>&1 \
    || { yellow "  ⚠ could not install ${CLAUDE_JAVA_LSP_PLUGIN}. By hand: claude plugin install ${CLAUDE_JAVA_LSP_PLUGIN} --scope user"; return 0; }
  green "  ✓ Claude Code: ${CLAUDE_JAVA_LSP_PLUGIN} (user scope)"
}

claude_plugin_installed() {
  python3 -c 'import json,sys; sys.exit(sys.argv[2] not in json.load(open(sys.argv[1])).get("plugins",{}))' \
    "${HOME}/.claude/plugins/installed_plugins.json" "$1" 2>/dev/null
}

# ---------- dev-tools check ----------

# An agent shell sources no rc file, so it has no sdkman entries and no JAVA_HOME.
agent_shell() {
  local path
  path="$(tr ':' '\n' <<<"$PATH" | grep -v '/\.sdkman/' | paste -sd:)"
  env -i HOME="$HOME" USER="${USER:-}" PATH="$path" bash -c "$1" 2>&1
}

CHECK_FAILED=0
ok() { green "  ✓ $1"; }
fail() { red "$1"; CHECK_FAILED=1; }
warn() { yellow "  ⚠ $1"; }

check_dev_tools() {
  step "Development tools the agents use"
  CHECK_FAILED=0
  local out

  out="$(agent_shell 'mvn -v')" || true
  if grep -q "Apache Maven ${MAVEN_VERSION}" <<<"$out" && grep -q 'Java version: 17\.' <<<"$out"; then
    ok "mvn ${MAVEN_VERSION} on Java 17, without sdkman in the shell"
  else
    fail "mvn in a non-interactive shell is not Maven ${MAVEN_VERSION} on Java 17: $(head -1 <<<"$out")"
  fi
  [[ "$(readlink "${SDKMAN_ROOT}/candidates/java/current" 2>/dev/null)" == *"${JDK_BUILD}" ]] \
    && ok "sdkman default java ${JDK_BUILD}" || fail "sdkman default java is not ${JDK_BUILD}"
  [[ -f "${HOME}/.m2/settings.xml" && "$(stat -c '%a' "${HOME}/.m2/settings.xml")" == 600 ]] \
    && ok "~/.m2/settings.xml (600)" || fail "~/.m2/settings.xml missing or not mode 600 (Nexus mirror)"

  [[ -x "${JDK_LSP_HOME}/bin/java" && -d "${JDTLS_HOME}/plugins" && -s "$LOMBOK_JAR" ]] \
    && agent_shell 'command -v jdtls' >/dev/null \
    && ok "jdtls ${JDTLS_VERSION} on PATH (JDK ${JDK_LSP}, lombok ${LOMBOK_VERSION})" \
    || fail "jdtls is not installed: run ./install.sh"
  if command_exists claude; then
    claude_plugin_installed "$CLAUDE_JAVA_LSP_PLUGIN" && ok "Claude Code plugin ${CLAUDE_JAVA_LSP_PLUGIN}" \
      || fail "Claude Code plugin ${CLAUDE_JAVA_LSP_PLUGIN} not installed"
  fi
  local pattern
  for pattern in "${LSP_IGNORES[@]}"; do
    git config --global --get core.excludesFile >/dev/null || grep -qxF "$pattern" "$GIT_IGNORE" 2>/dev/null \
      && ok "git ignores ${pattern} globally" || fail "${pattern} is not in ${GIT_IGNORE}"
  done

  local -A required=(
    [git]="branches, commits, PRs" [python3]="skill scripts" [uv]="MCP servers"
    [rtk]="command output filter" [kiro-cli]="the agents" [curl]="REST skills"
    [docker]="kevint services for ITs" [kevint]="local Postgres, Redis, Neo4j"
    [npx]="codegraph MCP server" [aws]="logs-metrics, LocalStack"
    [redpoints]="PRO/PRE psql, cache-ops. Install: uv tool install --index-url \"\$(pip config get global.index-url)\" redpoints-cli"
    [psql]="psql skill"
  )
  local cmd
  for cmd in $(printf '%s\n' "${!required[@]}" | sort); do
    agent_shell "command -v ${cmd}" >/dev/null && ok "${cmd}" || fail "${cmd} not on the agent PATH (${required[$cmd]})"
  done
  python3 -c 'import psycopg2' 2>/dev/null && ok "python3 psycopg2" || fail "python3 psycopg2 missing (localdb skill)"
  command_exists claude && ok "claude" || warn "claude not found — Claude Code agents unavailable"

  ((CHECK_FAILED == 0)) && green "✓ Every development tool is available" \
    || yellow "Some development tools are missing: the agents will fail where they need them."
  return "$CHECK_FAILED"
}
