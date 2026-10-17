#!/usr/bin/env bash
# Run Gemma 4 on the UNO Q as our own llama.cpp server, outside App Lab's containers, from the files the
# speed test (run_spike.sh) downloaded to ~/gemma-spike on the big /home disk. The Garden Steward app
# finds it by itself (python/brain.py: LLM_BASE_URL = "auto").
#
#   bash spike/serve_gemma.sh            # start in the background (photos on if a photo part is there)
#   VISION=0 bash spike/serve_gemma.sh   # text only: about 0.5-1 GB less memory, no photo check
#   bash spike/serve_gemma.sh status     # running? which model?
#   bash spike/serve_gemma.sh stop
set -euo pipefail

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "aarch64" ]; then
  echo "Run this ON THE UNO Q (App Lab's terminal, ssh arduino@<board-name>.local, or adb shell)."
  exit 1
fi

WORK="${WORK:-$HOME/gemma-spike}"
THREADS="${THREADS:-4}"
VISION="${VISION:-1}"
PORT="${PORT:-8080}"
PID_FILE="$WORK/serve.pid"
LOG="$WORK/serve.log"

running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

case "${1:-start}" in
  stop)
    if running; then kill "$(cat "$PID_FILE")"; rm -f "$PID_FILE"; echo "Stopped."; else echo "Not running."; fi
    exit 0 ;;
  status)
    if running; then
      echo "Running (pid $(cat "$PID_FILE")) on port $PORT. Models:"
      curl -s "http://127.0.0.1:$PORT/v1/models" | python3 -c "import json,sys; print([m['id'] for m in json.load(sys.stdin)['data']])"
      free -m | awk '/Mem:/ {print "Memory free: " $7 " of " $2 " MB"}'
    else
      echo "Not running."
    fi
    exit 0 ;;
  start) ;;
  *) echo "Usage: bash spike/serve_gemma.sh [start|stop|status]"; exit 1 ;;
esac

if running; then echo "Already running (pid $(cat "$PID_FILE")). Stop it with: bash spike/serve_gemma.sh stop"; exit 0; fi
[ -x "$WORK/pkg-cpu/bin/llama-server" ] || { echo "No llama.cpp in $WORK: run bash spike/run_spike.sh first."; exit 1; }

# The Gemma 4 file the speed test downloaded (the biggest one, if there are several), or MODEL_FILE=...
MODEL_FILE="${MODEL_FILE:-$(ls -S "$WORK"/*.gguf 2>/dev/null | grep -v mmproj | head -1 || true)}"
[ -n "$MODEL_FILE" ] && [ -f "$MODEL_FILE" ] || { echo "No Gemma 4 .gguf in $WORK: run bash spike/run_spike.sh first."; exit 1; }
NAME="$(basename "${MODEL_FILE%.gguf}")"

VISION_ARGS=()
if [ "$VISION" = "1" ]; then
  # The smallest photo part there is: the Q8_0 one needs about 0.4 GB less memory than the 0.99 GB one.
  MMPROJ="$(ls -Sr "$WORK"/*mmproj*.gguf 2>/dev/null | head -1 || true)"
  if [ -n "$MMPROJ" ]; then VISION_ARGS=(--mmproj "$MMPROJ"); else echo "No photo part (mmproj) in $WORK: text only."; fi
fi

export LD_LIBRARY_PATH="$WORK/pkg-cpu/lib"
# --host 0.0.0.0: App Lab's app container reaches the board through the Docker gateway (anyone on the
#   same Wi-Fi can reach it too, so stop it when you're done).
# -np 1: one conversation slot, so the unchanged start of each prompt is reused instead of read again.
nohup "$WORK/pkg-cpu/bin/llama-server" -m "$MODEL_FILE" "${VISION_ARGS[@]}" --alias "$NAME" \
  -c 4096 -np 1 -t "$THREADS" --host 0.0.0.0 --port "$PORT" \
  --reasoning off --reasoning-budget 0 > "$LOG" 2>&1 &
echo $! > "$PID_FILE"
echo "Starting Gemma 4: $NAME$([ ${#VISION_ARGS[@]} -gt 0 ] && echo " + photos ($(basename "$MMPROJ"))") on port $PORT. Log: $LOG"
for _ in $(seq 1 180); do
  if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null; then
    echo "Ready. Start the Garden Steward app in App Lab: it finds this server by itself."
    exit 0
  fi
  running || { echo "llama-server stopped. Last lines of $LOG:"; tail -20 "$LOG"; rm -f "$PID_FILE"; exit 1; }
  sleep 2
done
echo "Still loading. Check with: bash spike/serve_gemma.sh status"
