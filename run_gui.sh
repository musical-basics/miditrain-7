#!/bin/bash
# Serve the phase-inspector GUI. Serves the REPO ROOT so gui/ can fetch
# ../data/. PORT=xxxx ./run_gui.sh ; --no-open to skip the browser.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8137}"

# free the port if something (usually an old instance) holds it
PID=$(lsof -ti tcp:"$PORT" || true)
if [ -n "$PID" ]; then
  echo "killing previous server on port $PORT (pid $PID)"
  kill "$PID" 2>/dev/null || true
  sleep 0.3
fi

python3 run_all.py
echo
echo "GUI: http://localhost:$PORT/gui/"
if [ "$1" != "--no-open" ]; then
  (sleep 0.6; open "http://localhost:$PORT/gui/") &
fi
exec python3 -m http.server "$PORT" --bind 127.0.0.1
