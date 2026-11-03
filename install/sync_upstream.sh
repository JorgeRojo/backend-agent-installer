#!/usr/bin/env bash
# sync_upstream.sh — Clone backend-agent into a fresh temp dir.
# Depends on: ui.sh, helpers.sh, config.sh.

sync_upstream() {
  step "Step 2: Cloning ${UPSTREAM_BRANCH} of backend-agent"

  UPSTREAM_DIR="$(mktemp -d "${TMPDIR:-/tmp}/backend-agent-upstream.XXXXXX")"
  export UPSTREAM_DIR

  cyan "  clones -> ${UPSTREAM_REPO} (${UPSTREAM_BRANCH})"
  dim  "  into ${UPSTREAM_DIR}"
  git clone --quiet --branch "$UPSTREAM_BRANCH" --single-branch \
    "$UPSTREAM_REPO" "$UPSTREAM_DIR" </dev/null \
    || die "could not clone ${UPSTREAM_REPO} (SSH key / VPN?)."

  green "  ✓ ${UPSTREAM_BRANCH} @ $(git -C "$UPSTREAM_DIR" log -1 --format='%h %s')"
  [[ -f "${UPSTREAM_DIR}/agents/${AGENT}.json" ]] || die "upstream does not define ${AGENT}."
}
