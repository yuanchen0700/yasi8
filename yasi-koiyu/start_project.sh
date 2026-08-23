#!/usr/bin/env bash
# start_project.sh - Launch brand9 (local server + frp tunnel) in a persistent window.
# Keep this window open while using the app; close it or press Ctrl+C to stop.
# You can also stop it from another terminal: bash stop_project.sh

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJ_DIR"

PIDFILE="$PROJ_DIR/.brand9.pids"

# Already running? Judge by REAL state (port + HTTP probe), not the PID file:
# after crashes MSYS PIDs get recycled (kill -0 lies) and orphaned processes
# can squat the port while being non-responsive.
if netstat -ano 2>/dev/null | grep ":8996" | grep -qi "LISTENING"; then
  if curl -s --max-time 3 "http://127.0.0.1:8996/" >/dev/null; then
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
# PID file is stale after a crash; remove it so a fresh start can run.
rm -f "$PIDFILE"

# Kill children when this window closes (Ctrl+C / window X), then drop PID file.
cleanup() {
  kill "$SERVER_PID" "$FRP_PID" 2>/dev/null
  rm -f "$PIDFILE"
}
trap 'cleanup' EXIT INT TERM

# Activate virtual environment if present
if [ -f ".venv/Scripts/activate" ]; then
  source ".venv/Scripts/activate"
fi

echo "=================== brand9 launcher ==================="

# 1) Python HTTP server (port 8996)
# Logs go to server.log (NOT the console pipe): if this script's parent shell
# dies, the orphaned server keeps writing to a file instead of a broken pipe,
# which previously made the server unresponsive ("empty reply").
echo "[1/2] Starting server on http://127.0.0.1:8996 ..."
python server.py >> "$PROJ_DIR/server.log" 2>&1 &
SERVER_PID=$!
sleep 2
# NOTE: use bash redirect >/dev/null, NOT curl -o /dev/null (MSYS curl -o misbehaves, exit 23)
if ! curl -s --max-time 5 "http://127.0.0.1:8996/" >/dev/null; then
  echo "ERROR: server did not start. Check $PROJ_DIR/server.log"
  read -rsp "Press Enter to close this window..." -n1 key
  exit 1
fi
echo "      server OK  (PID $SERVER_PID)"

# 2) frp tunnel (local 8996 -> public 118.89.62.241:8649)
# NOTE: use Windows-style paths (C:/...) — frpc.exe is a native Windows program
# and does NOT understand MSYS /c/... paths.
FRP_DIR="C:/Users/Cheng/Downloads/heermes/_netcross/frp_0.61.0_windows_amd64"
FRP_PATH="$FRP_DIR/frpc.exe"
FRP_CFG="$FRP_DIR/frpc.toml"
FRP_PID=""
if [ -f "$FRP_PATH" ] && [ -f "$FRP_CFG" ]; then
  echo "[2/2] Starting frp tunnel (public http://118.89.62.241:8649) ..."
  "$FRP_PATH" -c "$FRP_CFG" >> "$PROJ_DIR/frp.log" 2>&1 &
  FRP_PID=$!
  sleep 2
  if curl -s --max-time 10 "http://118.89.62.241:8649/" >/dev/null; then
    echo "      tunnel OK  (PID $FRP_PID)"
  else
    echo "      WARNING: frpc started but public URL not reachable yet;"
    echo "               it may still be logging in - check $PROJ_DIR/frp.log"
  fi
else
  echo "[2/2] WARNING: frpc.exe or frpc.toml not found in $FRP_DIR - tunnel skipped."
fi

echo "$SERVER_PID $FRP_PID" > "$PIDFILE"

echo ""
echo "brand9 is RUNNING."
echo "  Local : http://127.0.0.1:8996/"
echo "  Public: http://118.89.62.241:8649/"
echo ""
echo "Keep this window open. Close it (or Ctrl+C) to stop brand9,"
echo "or run from another terminal:  bash stop_project.sh"
echo "-------------------------------------------------------"

wait   # block forever -> window stays open, logs stream here
