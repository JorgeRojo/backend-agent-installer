#!/usr/bin/env bash
# postgres-mcp.sh <database> <uvx args...> — local/dev Postgres MCP, one database per server.
# postgres-mcp never closes its pool: every Kiro, Claude and agy session keeps one connection per
# server open, which exhausts max_connections. Idle sessions are dropped after 5 min instead.
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
db="$1"
shift
export DATABASE_URI="postgresql://${LOCAL_PG_USER}:${LOCAL_PG_PASSWORD}@${LOCAL_PG_URL}/${db}?application_name=backend-dev-${db}&options=-c%20idle_session_timeout%3D300000"
exec uvx "$@"
