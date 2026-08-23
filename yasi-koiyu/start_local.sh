#!/usr/bin/env bash
# start_local.sh - Launch brand9 locally over HTTPS with a mkcert cert
# (ZeroTier IP + 127.0.0.1). No frp tunnel - this is for direct LAN/VPN access.
# Usage:  bash start_local.sh      (Windows Git Bash; server deployment uses start_project.sh)

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJ_DIR"

PIDFILE="$PROJ_DIR/.brand9.pids"

# Same real-state check as start_project.sh (port + HTTP probe).
if netstat -ano 2>/dev/null | grep ":8996" | grep -qi "LISTENING"; then
  if curl -ks --max-time 3 "https://127.0.0.1:8996/" >/dev/null 2>&1; then
    echo "brand9 is already running and responding on port 8996."
    echo "Stop it first with:  bash stop_project.sh"
    read -rsp "Press Enter to close this window..." -n1 key
    exit 1
  else
    echo "Port 8996 is occupied by a stuck (non-responsive) process - killing it."
    BUSY_PID=$(netstat -ano 2>/dev/null | grep ":8996" | grep -i "LISTENING" | awk '{print $NF}' | head -1)
    if [ -n "$BUSY_PID" ]; then
      MSYS_NO_PATHCONV=1 taskkill /F /PID "$BUSY_PID" >/dev/null 2>&1
      sleep 1
    fi
  fi
fi
rm -f "$PIDFILE"

cleanup() {
  kill "$SERVER_PID" 2>/dev/null
  rm -f "$PIDFILE"
}
trap 'cleanup' EXIT INT TERM

if [ -f ".venv/Scripts/activate" ]; then
  source ".venv/Scripts/activate"
fi

echo "=================== brand9 local HTTPS launcher ==================="

# Sanity check: cert + key must exist (run mkcert first, see fun/net-access/report.md)
if [ ! -f "10.110.218.198+1.pem" ] || [ ! -f "10.110.218.198+1-key.pem" ]; then
  echo "ERROR: mkcert certificate/key missing in $PROJ_DIR"
  echo "       Run: mkcert -install && mkcert 10.110.218.198 127.0.0.1"
  read -rsp "Press Enter to close this window..." -n1 key
  exit 1
fi

echo "[1/1] Starting HTTPS server on port 8996 ..."
BRAND9_TLS=1 node server.js >> "$PROJ_DIR/server.log" 2>&1 &
SERVER_PID=$!
sleep 2

if ! curl -ks --max-time 5 "https://127.0.0.1:8996/" >/dev/null; then
  echo "ERROR: server did not start. Check $PROJ_DIR/server.log"
  read -rsp "Press Enter to close this window..." -n1 key
  exit 1
fi
echo "      server OK  (PID $SERVER_PID)"

echo "$SERVER_PID 0" > "$PIDFILE"

# Detect ZeroTier / other LAN IPs to advertise.
IPS=$(ipconfig 2>/dev/null | grep -A6 -i "ZeroTier" | grep -E "IPv4" | sed -E 's/.*: ([0-9.]+).*/\1/' | grep -v "^169\.254\.")
if [ -z "$IPS" ]; then
  IPS=$(ipconfig 2>/dev/null | grep -E "IPv4" | sed -E 's/.*: ([0-9.]+).*/\1/' | grep -v "^127\." | grep -v "^169\.254\.")
fi

echo ""
echo "brand9 is RUNNING (HTTPS)."
echo "  Local : https://127.0.0.1:8996/"
if [ -n "$IPS" ]; then
  for ip in $IPS; do
    echo "  Remote: https://$ip:8996/   (via ZeroTier/LAN)"
  done
fi
echo ""
echo "Keep this window open. Close it (or Ctrl+C) to stop brand9,"
echo "or run from another terminal:  bash stop_project.sh"
echo "-------------------------------------------------------"

wait
