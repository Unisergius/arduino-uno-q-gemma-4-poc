#!/usr/bin/env bash
# Phase 0 spike: can the Arduino UNO Q run Gemma 4 E2B fast enough?
# Run this ON THE BOARD (App Lab terminal, ssh or adb shell). Stop any running App Lab app first to free memory.
#
#   bash spike/run_spike.sh                      # biggest Gemma 4 E2B that fits the disk: speed, memory, a decision, a photo
#   VISION=0 bash spike/run_spike.sh             # text only: no photo part (less disk and memory)
#   MODEL=small bash spike/run_spike.sh          # pick a size yourself: full | q4 | small | tiny (list below)
#   MODEL_URL=<.gguf> MMPROJ_URL=<.gguf> bash spike/run_spike.sh   # any other Gemma 4 file
#   PHOTO=~/garden.jpg bash spike/run_spike.sh   # your own photo for the photo test (default: the "sick" test drawing)
#   INSTALL_FOR_APPLAB=1 bash spike/run_spike.sh # ...and move the model into App Lab's models folder (needs room on /)
#
# Afterwards, serve Gemma 4 for the app with: bash spike/serve_gemma.sh  (recommended over INSTALL_FOR_APPLAB)
set -euo pipefail

# This downloads a llama.cpp built for the UNO Q's Linux (arm64): it cannot run on a Mac or a PC.
if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "aarch64" ]; then
  echo "This test must run ON THE UNO Q, not on this computer ($(uname -s) $(uname -m))."
  echo
  echo "Open a terminal on the board first, one of:"
  echo "  - App Lab's built-in terminal"
  echo "  - from this computer: ssh arduino@<board-name>.local   (the password you chose in App Lab's setup)"
  echo "  - over USB: adb shell"
  echo
  echo "Then, on the board:"
  echo "  git clone https://github.com/Unisergius/arduino-uno-q-gemma-4-poc.git"
  echo "  cd arduino-uno-q-gemma-4-poc && bash spike/run_spike.sh"
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$HOME/gemma-spike}"
THREADS="${THREADS:-4}"
VISION="${VISION:-1}"
# Arduino's own prebuilt llama.cpp for the UNO Q (the same build App Lab's LLM brick runs).
LLAMA_URL="https://github.com/arduino/app-bricks-py/releases/download/llamacpp%2F20260918/llamacpp-cpu-20260918.tar.gz"

# Gemma 4 E2B in four sizes, biggest first: "<model url> <MB> <photo part url> <MB>".
#   full : Google's QAT Q4_0 (the file Arduino ships for the VENTUNO Q) + its photo part  = 4.3 GB
#   q4   : ggml-org Q4_0 + a smaller (Q8_0) photo part                                    = 3.4 GB
#   small: unsloth Q3_K_M + the smaller photo part                                       = 3.1 GB
#   tiny : unsloth UD-Q2_K_XL + the smaller photo part                                   = 3.0 GB
HF=https://huggingface.co
MMPROJ_Q8="$HF/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/mmproj-gemma-4-E2B-it-Q8_0.gguf"
preset() {
  case "$1" in
    full)  echo "$HF/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/main/gemma-4-E2B_q4_0-it.gguf 3350 $HF/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/main/gemma-4-E2B-it-mmproj.gguf 990" ;;
    q4)    echo "$HF/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_0.gguf 2840 $MMPROJ_Q8 560" ;;
    small) echo "$HF/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q3_K_M.gguf 2540 $MMPROJ_Q8 560" ;;
    tiny)  echo "$HF/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-UD-Q2_K_XL.gguf 2400 $MMPROJ_Q8 560" ;;
    *)     return 1 ;;
  esac
}

step() { echo; echo "=== $*"; }
mkdir -p "$WORK"
cd "$WORK"

step "0/5  Room on the board"
FREE_DISK_MB=$(df -Pm . | awk 'NR==2 {print $4}')
FREE_RAM_MB=$(free -m | awk '/Mem:/ {print $7}')
echo "Free disk: ${FREE_DISK_MB} MB   Free memory: ${FREE_RAM_MB} MB"
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qi llama; then
  echo "Note: an App Lab LLM container is running and uses memory. Stop the App Lab app for a fair test."
fi

# MB still to download for a model (+ photo part), plus a little room to spare.
still_needed_mb() {
  local need=300
  [ -f "$(basename "$1")" ] || need=$((need + $2))
  if [ "$VISION" = "1" ] && [ ! -f "$(basename "$3")" ]; then need=$((need + $4)); fi
  echo "$need"
}

if [ -n "${MODEL_URL:-}" ]; then
  CHOSEN="your MODEL_URL"
  MMPROJ_URL="${MMPROJ_URL:-$MMPROJ_Q8}"
else
  CHOSEN=""
  for name in ${MODEL:-full q4 small tiny}; do
    p="$(preset "$name")" || { echo "Unknown MODEL=$name - use full, q4, small or tiny"; exit 1; }
    read -r url size murl msize <<< "$p"
    need="$(still_needed_mb "$url" "$size" "$murl" "$msize")"
    if [ "$need" -le "$FREE_DISK_MB" ]; then
      CHOSEN="$name"; MODEL_URL="$url"; MMPROJ_URL="$murl"
      break
    fi
    echo "  '$name' needs about $need MB free: too big for this disk"
  done
  if [ -z "$CHOSEN" ]; then
    echo "Not enough free disk for Gemma 4 E2B: the smallest needs about 3.3 GB with photos, 2.7 GB with VISION=0."
    echo "Free some space (old models in /var/lib/arduino-app-cli/models, files in ~), or run: VISION=0 bash spike/run_spike.sh"
    exit 1
  fi
fi
MODEL_FILE="$(basename "$MODEL_URL")"
MMPROJ_FILE="$(basename "$MMPROJ_URL")"
MODEL_NAME="${MODEL_FILE%.gguf}"
VISION_ARGS=()
[ "$VISION" = "1" ] && VISION_ARGS=(--mmproj "$MMPROJ_FILE")
echo "Using: $CHOSEN -> $MODEL_FILE$([ "$VISION" = "1" ] && echo " + $MMPROJ_FILE")"

step "1/5  llama.cpp (prebuilt for the UNO Q)"
if [ ! -x pkg-cpu/bin/llama-server ]; then
  curl -L --fail -o llamacpp.tar.gz "$LLAMA_URL"
  tar -xzf llamacpp.tar.gz
  rm llamacpp.tar.gz
fi
export LD_LIBRARY_PATH="$WORK/pkg-cpu/lib"
BIN="$WORK/pkg-cpu/bin"
"$BIN/llama-server" --version || { echo "llama-server does not start. If the error above mentions libgomp: sudo apt install libgomp1"; exit 1; }

step "2/5  Gemma 4 E2B - needs internet this one time"
[ -f "$MODEL_FILE" ] || curl -L --fail -o "$MODEL_FILE" "$MODEL_URL"
if [ "$VISION" = "1" ]; then [ -f "$MMPROJ_FILE" ] || curl -L --fail -o "$MMPROJ_FILE" "$MMPROJ_URL"; fi
df -h . | tail -1

step "3/5  Raw speed with llama-bench (a few minutes)"
"$BIN/llama-bench" -m "$MODEL_FILE" -t "$THREADS" -p 256 -n 64 -r 2 -o md | tee bench.md

step "4/5  One real garden decision (and a photo check) through llama-server"
"$BIN/llama-server" -m "$MODEL_FILE" "${VISION_ARGS[@]}" --alias "$MODEL_NAME" \
  -c 4096 -t "$THREADS" --host 127.0.0.1 --port 8080 --reasoning off --reasoning-budget 0 > server.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
echo "Waiting for the model to load..."
for _ in $(seq 1 180); do
  curl -sf http://127.0.0.1:8080/health > /dev/null && break
  kill -0 $SERVER 2>/dev/null || { echo "llama-server stopped - last lines of server.log:"; tail -20 server.log; exit 1; }
  sleep 2
done
PHOTO_ARGS=()
if [ "$VISION" = "1" ]; then
  PHOTO="${PHOTO:-$HERE/../app/garden-steward/assets/test-photos/sick.png}"
  PHOTO_ARGS=(--photo "$PHOTO")
fi
python3 "$HERE/decide_once.py" --url http://127.0.0.1:8080/v1 --model "$MODEL_NAME" "${PHOTO_ARGS[@]}" | tee decision.md

step "5/5  Memory"
PEAK_MB=$(( $(awk '/VmHWM/ {print $2}' /proc/$SERVER/status) / 1024 ))
FREE_NOW_MB=$(free -m | awk '/Mem:/ {print $7}')
TOTAL_MB=$(free -m | awk '/Mem:/ {print $2}')

{
  echo
  echo "## Gemma 4 E2B on the UNO Q - results"
  echo
  echo "| What | Value |"
  echo "|---|---|"
  echo "| Model file | ${MODEL_FILE} (size: ${CHOSEN}, photos: ${VISION}) |"
  echo "| llama-server peak memory | ${PEAK_MB} MB |"
  echo "| Memory free before / now / total | ${FREE_RAM_MB} / ${FREE_NOW_MB} / ${TOTAL_MB} MB |"
  echo "| Free disk before the download | ${FREE_DISK_MB} MB |"
  echo "| Threads | ${THREADS} |"
  echo
  echo "Speed (llama-bench: pp256 = reading a prompt, tg64 = writing an answer):"
  echo
  cat bench.md
  echo
  cat decision.md
  echo
  echo "Power: read your USB-C power meter while idle and during step 4, and add the watts here."
} | tee results.md

if [ "${INSTALL_FOR_APPLAB:-}" = "1" ]; then
  step "Extra: moving the model to where App Lab's LLM brick serves it (no second copy on the disk)"
  # Arduino's llama.cpp runner serves every .gguf in its models folder, named after the file, and pairs
  # it with an *mmproj*.gguf from the same folder (containers/ai/llamacpp-runner in arduino/app-bricks-py).
  DEST=/var/lib/arduino-app-cli/models/llamacpp/gemma-4-E2B  # VERIFY: the folder the runner mounts as /models
  sudo mkdir -p "$DEST"
  # Keep exactly one Gemma 4 model and one photo part in the folder, so the runner pairs the right ones.
  sudo find "$DEST" -maxdepth 1 -name '*.gguf' ! -name "$MODEL_FILE" ! -name "$MMPROJ_FILE" -print -delete
  FILES=("$MODEL_FILE")
  [ "$VISION" = "1" ] && FILES+=("$MMPROJ_FILE")
  # App Lab's models folder sits on the small root disk: moving a 3-4 GB model there can fill it up.
  NEED_MB=$(( $(du -mL "${FILES[@]}" | awk '{s += $1} END {print s}') + 500 ))
  ROOM_MB=$(df -Pm "$(dirname "$DEST")" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
  if [ "$ROOM_MB" -lt "$NEED_MB" ]; then
    echo "Not enough room in $(dirname "$DEST"): ${ROOM_MB} MB free, ${NEED_MB} MB needed. Nothing was moved."
    echo "Run Gemma 4 as our own server instead (no copying): bash spike/serve_gemma.sh"
    exit 1
  fi
  for f in "${FILES[@]}"; do
    if [ ! -L "$f" ]; then
      sudo mv "$f" "$DEST/$f"
      ln -s "$DEST/$f" "$f"  # so a rerun of this test finds it without downloading again
    fi
  done
  ls -la "$DEST"
  echo "App Lab serves it as: $MODEL_NAME  (the Garden Steward app finds any installed Gemma 4 by itself)"
fi

echo
echo "Done. Paste $WORK/results.md back into the chat."
echo "To run Gemma 4 for the Garden Steward app: bash spike/serve_gemma.sh"
