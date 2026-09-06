#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$ROOT_DIR/web"
HOST="${KOTPRINTER_HOST:-0.0.0.0}"
PORT="${KOTPRINTER_PORT:-8000}"
LAN_HOST="${KOTPRINTER_LAN_HOST:-}"
REBUILD="${KOTPRINTER_REBUILD:-0}"

cd "$ROOT_DIR"

if [[ ! -d "$WEB_DIR/node_modules" ]]; then
  echo "[i] Installing frontend dependencies..."
  (cd "$WEB_DIR" && npm install)
fi

if [[ "$REBUILD" == "1" || ! -f "$WEB_DIR/dist/index.html" ]]; then
  echo "[i] Building frontend..."
  (cd "$WEB_DIR" && npm run build)
fi

if [[ -z "$LAN_HOST" ]]; then
  LAN_HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi

echo "[i] KotPrinter web UI"
echo "    Local: http://127.0.0.1:$PORT/"
if [[ -n "$LAN_HOST" ]]; then
  echo "    LAN:   http://$LAN_HOST:$PORT/"
else
  echo "    LAN:   set KOTPRINTER_LAN_HOST to print a LAN URL"
fi
echo
echo "[i] Stop with Ctrl+C."

exec python3 -m kotprinter.server \
  --host "$HOST" \
  --port "$PORT" \
  --project-root "$ROOT_DIR"
