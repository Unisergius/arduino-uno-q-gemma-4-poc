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

## Which Gemma 4 file it uses
The script checks the free disk first and takes the biggest Gemma 4 E2B that fits (it says which):

| Size | Files | Disk |
|---|---|---|
| `full` | Google's QAT Q4_0 (the file Arduino ships for the VENTUNO Q) + its photo part | 4.3 GB |
| `q4` | ggml-org Q4_0 + a smaller (Q8_0) photo part | 3.4 GB |
| `small` | unsloth Q3_K_M + the smaller photo part | 3.1 GB |
| `tiny` | unsloth UD-Q2_K_XL + the smaller photo part | 3.0 GB |

Smaller = a little less accurate, and less memory. The photo test uses the app's "sick" test drawing
unless you pass `PHOTO=...`; the right answer is "sick".

## If it is too slow or too big
- Out of memory, or no size fits the disk: `VISION=0 bash spike/run_spike.sh` (text only, 0.6–1 GB less).
- Force a smaller size: `MODEL=small bash spike/run_spike.sh` (or `tiny`).
- Try fewer or more threads: `THREADS=3 bash spike/run_spike.sh`.
- Last resort: Gemma 3 1B (App Lab offers it on the UNO Q) for the "Decide" job only.

## Running Gemma 4 for the app (after the test)

```bash
bash spike/serve_gemma.sh            # starts Gemma 4 in the background from ~/gemma-spike
bash spike/serve_gemma.sh status     # running? which model? free memory
bash spike/serve_gemma.sh stop
```
It runs outside App Lab's containers, from the files the test already downloaded to `~/gemma-spike`:
nothing is copied, and App Lab's LLM container limit doesn't apply. `SMALL_PHOTO=1` first downloads
ggml-org's 0.56 GB photo part, which needs about 0.4 GB less memory than Google's 0.99 GB one (tested with
Google's QAT model: same verdicts on both test drawings). Old prompts kept for reuse are capped at 256 MB. It uses the smallest photo
part in `~/gemma-spike` (`VISION=0` for text only), and one conversation slot so the unchanged start of
each prompt is reused. The Garden Steward app finds it by itself. Run it again after a reboot.

## App Lab and Gemma 4 (not needed with serve_gemma.sh)
App Lab's model list offers Gemma 4 only on the VENTUNO Q, but its llama.cpp runner serves **every `.gguf`
file in its models folder**, named after the file (see `containers/ai/llamacpp-runner` in Arduino's
`app-bricks-py`). `INSTALL_FOR_APPLAB=1` **moves** the files there (no second copy on the disk) and leaves a
link behind, and the Garden Steward app picks up whichever Gemma 4 it finds.
