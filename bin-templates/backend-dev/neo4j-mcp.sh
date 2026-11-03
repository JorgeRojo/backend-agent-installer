#!/usr/bin/env bash
# neo4j-mcp.sh <DEV|PRE|PRO> <uvx args...> — Neo4j Cypher MCP for one environment.
# shellcheck source=/dev/null
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
uri_var="NEO4J_${1}_URI"
pw_var="NEO4J_${1}_PASSWORD"
shift
export NEO4J_URI="${!uri_var:-}" NEO4J_PASSWORD="${!pw_var:-}"
exec uvx "$@"
