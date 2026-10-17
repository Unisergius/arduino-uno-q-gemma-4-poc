#!/usr/bin/env bash
# Phase 0 spike: can the Arduino UNO Q run Gemma 4 E2B fast enough?
# Run this ON THE BOARD (App Lab terminal or SSH). Stop any running App Lab app first to free memory.
#
#   bash spike/run_spike.sh                      # speed, memory, one garden decision
#   PHOTO=~/garden.jpg bash spike/run_spike.sh   # ...and a "See" test on your photo
#   INSTALL_FOR_APPLAB=1 bash spike/run_spike.sh # ...and copy the model where App Lab's LLM brick finds it
#   VISION=0 bash spike/run_spike.sh             # text only: skips the 1 GB vision part (less memory)
#   MODEL_URL=<smaller .gguf> bash spike/run_spike.sh  # try a smaller file if memory is too tight
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
# Arduino's own prebuilt llama.cpp for the UNO Q (the same build App Lab's LLM brick runs).
LLAMA_URL="https://github.com/arduino/app-bricks-py/releases/download/llamacpp%2F20260918/llamacpp-cpu-20260918.tar.gz"
MODEL_URL="${MODEL_URL:-https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/main/gemma-4-E2B_q4_0-it.gguf}"
MMPROJ_URL="${MMPROJ_URL:-https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/main/gemma-4-E2B-it-mmproj.gguf}"
VISION="${VISION:-1}"
MODEL_FILE="$(basename "$MODEL_URL")"
MMPROJ_FILE="$(basename "$MMPROJ_URL")"
MODEL_NAME="${MODEL_FILE%.gguf}"
VISION_ARGS=()
[ "$VISION" = "1" ] && VISION_ARGS=(--mmproj "$MMPROJ_FILE")

step() { echo; echo "=== $*"; }
mkdir -p "$WORK"
cd "$WORK"

step "1/5  llama.cpp (prebuilt for the UNO Q)"
if [ ! -x pkg-cpu/bin/llama-server ]; then
  curl -L --fail -o llamacpp.tar.gz "$LLAMA_URL"
  tar -xzf llamacpp.tar.gz
  rm llamacpp.tar.gz
fi
export LD_LIBRARY_PATH="$WORK/pkg-cpu/lib"
BIN="$WORK/pkg-cpu/bin"
"$BIN/llama-server" --version || { echo "llama-server does not start. If the error above mentions libgomp: sudo apt install libgomp1"; exit 1; }

step "2/5  Gemma 4 E2B ($MODEL_FILE) + vision part if VISION=1 - needs internet this one time"
[ -f "$MODEL_FILE" ] || curl -L --fail -o "$MODEL_FILE" "$MODEL_URL"
if [ "$VISION" = "1" ]; then [ -f "$MMPROJ_FILE" ] || curl -L --fail -o "$MMPROJ_FILE" "$MMPROJ_URL"; fi
df -h "$WORK" | tail -1

step "3/5  Raw speed with llama-bench (a few minutes)"
"$BIN/llama-bench" -m "$MODEL_FILE" -t "$THREADS" -p 256 -n 64 -r 2 -o md | tee bench.md

step "4/5  One real garden decision through llama-server"
"$BIN/llama-server" -m "$MODEL_FILE" "${VISION_ARGS[@]}" --alias "$MODEL_NAME" \
  -c 4096 -t "$THREADS" --host 127.0.0.1 --port 8080 --reasoning off --reasoning-budget 0 > server.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
echo "Waiting for the model to load..."
for _ in $(seq 1 180); do
  curl -sf http://127.0.0.1:8080/health > /dev/null && break
  sleep 2
done
PHOTO_ARGS=()
[ -n "${PHOTO:-}" ] && [ "$VISION" = "1" ] && PHOTO_ARGS=(--photo "$PHOTO")
python3 "$HERE/decide_once.py" --url http://127.0.0.1:8080/v1 --model "$MODEL_NAME" "${PHOTO_ARGS[@]}" | tee decision.md

step "5/5  Memory"
PEAK_MB=$(( $(awk '/VmHWM/ {print $2}' /proc/$SERVER/status) / 1024 ))
FREE_MB=$(free -m | awk '/Mem:/ {print $7}')
TOTAL_MB=$(free -m | awk '/Mem:/ {print $2}')

{
  echo
  echo "## Gemma 4 E2B on the UNO Q - results"
  echo
  echo "| What | Value |"
  echo "|---|---|"
  echo "| llama-server peak memory | ${PEAK_MB} MB |"
  echo "| Board memory available now / total | ${FREE_MB} / ${TOTAL_MB} MB |"
  echo "| Model file | ${MODEL_FILE} (vision: ${VISION}) |"
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
  step "Extra: copying the model where App Lab's LLM brick looks for models"
  # VERIFY: App Lab's llama.cpp runner serves every .gguf in this folder (file name = model name)
  # and pairs it with an *mmproj*.gguf in the same folder.
  DEST=/var/lib/arduino-app-cli/models/llamacpp/gemma-4-E2B
  sudo mkdir -p "$DEST"
  sudo cp "$MODEL_FILE" "$DEST/$MODEL_FILE"
  if [ "$VISION" = "1" ]; then sudo cp "$MMPROJ_FILE" "$DEST/$MMPROJ_FILE"; fi
  echo "In app/garden-steward/python/config.py, set LLM_MODEL = \"$MODEL_NAME\""
  ls -la "$DEST"
fi

echo
echo "Done. Paste $WORK/results.md back into the chat."
