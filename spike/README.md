# Phase 0 spike: does Gemma 4 run well enough on the UNO Q?

One script answers the go/no-go question from `docs/design.md`: how fast Gemma 4 E2B is on the
board, how much memory it needs, and whether one real garden decision comes back in under 90 seconds.

> **Heads-up:** Arduino officially lists Gemma 4 E2B for the bigger VENTUNO Q. For the UNO Q it lists
> Gemma 3 1B and Qwen 3.5 0.8B. It should still run on the 4 GB UNO Q with llama.cpp, and this
> spike is how we find out.

## What you need
- The UNO Q 4 GB, powered and on Wi-Fi with internet **this one time** (to download ~4.5 GB).
- About 6 GB free disk space.
- Optional: a USB-C power meter between the charger and the board, to read the watts.
- Optional: a photo of your paper garden copied to the board (for the vision test).

## Steps
1. In App Lab, **stop any running app** (it frees memory).
2. Open a terminal **on the board**, not on your computer (the script stops if you run it on a Mac or PC):
   - App Lab's built-in terminal, or
   - from your computer: `ssh arduino@<board-name>.local` (the password you chose in App Lab's setup), or
   - over USB: `adb shell`.
3. Get this repository onto the board, for example:
   ```bash
   git clone https://github.com/Unisergius/arduino-uno-q-gemma-4-poc.git
   cd arduino-uno-q-gemma-4-poc
   ```
4. Run:
   ```bash
   bash spike/run_spike.sh
   ```
   With a photo: `PHOTO=~/garden.jpg bash spike/run_spike.sh`
5. It takes 10–30 minutes, mostly the download. At the end it prints a **results table** and saves it
   to `~/gemma-spike/results.md`. **Paste that table back into the chat.**
6. If the results look good, run it once more with `INSTALL_FOR_APPLAB=1` so the Garden Steward app
   can use the model (it asks for your password because it copies into a system folder).

## What "good" looks like
| Measure | Good enough | Why |
|---|---|---|
| One decision | under 90 s | Gemma decides every 2 simulated hours = every 2 real minutes |
| Writing speed (tg64) | 2+ tok/s | a decision is about 110 tokens |
| Peak memory | under ~2.5 GB | App Lab's LLM container is limited to 2.5 GB |

For comparison: on a 4-core x86 cloud machine the same decision took about 8 s (16 tok/s).
Google measured about 8 tok/s on a Raspberry Pi 5. We expect roughly 2–4 tok/s on the UNO Q.

## If it is too slow or too big
The model file is 3.35 GB and the vision part 0.99 GB, on a board with 4 GB of memory, so **memory is
the biggest risk**. Try these in order:
- Text only, without the 1 GB vision part: `VISION=0 bash spike/run_spike.sh`.
- A smaller file (lower precision, slightly less smart), e.g. 2.5 GB:
  `MODEL_URL=https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q3_K_M.gguf bash spike/run_spike.sh`
  (even smaller: `gemma-4-E2B-it-UD-Q2_K_XL.gguf`, 2.4 GB). The script prints the `LLM_MODEL` name to put in `config.py`.
- Try fewer or more threads: `THREADS=3 bash spike/run_spike.sh`.
- Use Gemma 3 1B (officially supported on the UNO Q) for the "Decide" job only.
- Keep Gemma 4 for the photo check, which only runs when you press the button.
