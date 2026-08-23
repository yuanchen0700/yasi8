#!/usr/bin/env bash
# stop_project.sh - Stop brand9 server + frp tunnel (started by start_project.sh).
# Safe to run anytime; also cleans up processes that were started manually.

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJ_DIR"

PIDFILE="$PROJ_DIR/.brand9.pids"
stopped=0

# --- 1) Kill PIDs recorded by start_project.sh ---
if [ -f "$PIDFILE" ]; then
  read -r SERVER_PID FRP_PID < "$PIDFILE"
  for pid in "$SERVER_PID" "$FRP_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      echo "Stopped process PID $pid"
      stopped=1
    fi
  done
  rm -f "$PIDFILE"
fi

# --- 2) Fallback: anything still listening on port 8996 ---
LISTEN_PID=$(netstat -ano 2>/dev/null | grep ":8996" | grep -i "LISTENING" | awk '{print $NF}' | head -1)
if [ -n "$LISTEN_PID" ]; then
  MSYS_NO_PATHCONV=1 taskkill /F /PID "$LISTEN_PID" >/dev/null 2>&1
  echo "Stopped server on port 8996 (PID $LISTEN_PID)"
  stopped=1
fi

# --- 3) Fallback: any remaining frpc.exe tunnel process ---
if tasklist 2>/dev/null | grep -qi "frpc.exe"; then
  MSYS_NO_PATHCONV=1 taskkill /F /IM frpc.exe >/dev/null 2>&1
  echo "Stopped frpc.exe tunnel"
  stopped=1
fi

if [ "$stopped" -eq 1 ]; then
  echo "brand9 has been stopped."
else
  echo "brand9 was not running (nothing to stop)."
fi
