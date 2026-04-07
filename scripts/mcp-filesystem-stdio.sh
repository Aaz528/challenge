#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_JS="$ROOT_DIR/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"

if [[ ! -f "$SERVER_JS" ]]; then
  echo "MCP filesystem package is not installed." >&2
  echo "Run: cd \"$ROOT_DIR\" && npm install @modelcontextprotocol/server-filesystem" >&2
  exit 1
fi

exec node "$SERVER_JS" "$@"
