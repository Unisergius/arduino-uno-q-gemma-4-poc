# Briefing for an AI agent working on this app (App Lab Agentic Mode, Claude Code, …)

**Garden Steward – Paper Garden demo.** Gemma 4 E2B, running locally on this Arduino UNO Q, decides when to
water a garden drawn on paper. The STM32 sketch enforces the safety limits. **No internet at runtime**:
the only network use is the local llama.cpp server (App Lab's `arduino:llm` brick) and the local web page.

## Files
- `sketch/sketch.ino`: MCU side. Reads the DFRobot Gravity sensors, drives the relay "pump", the LEDs and the
  LED matrix, and **enforces the safety limits**. Functions exposed over the Bridge: `water`,
  `read_sensors`, `set_sim_state`, `show`.
- `python/main.py`: entry point on the board (WebUI on port 7000, `Bridge`, `App.run`).
- `python/steward.py`: the loop (garden clock, Gemma jobs on a worker thread, log, web API).
- `python/brain.py`: Gemma's three jobs (Decide / See / Explain) via llama.cpp's OpenAI-style API with
  JSON-schema output, plus the fallback rule.
- `python/stats.py`: turns readings into the text Gemma reads (Python does all comparisons).
- `python/simulation.py`, `python/sensors.py`, `python/config.py`: simulated garden, raw→units, all settings.
- `python/laptop.py`: test environment without the board (not used on the board).
- `assets/`: the web page; `assets/test-photos/` holds the healthy/sick drawings used when there is no camera.

## Rules – do not break these
1. **Never weaken the safety limits** (`MAX_PUMP_S`, `MIN_INTERVAL_MIN`, `MAX_PER_DAY`, `BATTERY_FLOOR` in
   `sketch.ino`, and the same values in `config.py`) unless the user explicitly asks. Keep both files in sync.
2. **Wiring is 3.3 V logic.** Never suggest 5 V on A0–A5. D3 is not used. Pins: A0 knob, A1 soil probe,
   A2 LM35, A3 light, A4 steam (rain), D2 yellow button, D4 relay, D5 blue LED, D6 red LED.
3. **No cloud calls.** Don't add internet APIs. Gemma runs on the board.
4. Keep Gemma's outputs short and schema-constrained (it is slow on this board, ~2–4 tokens/s expected).

## First run on the board: check these, in this order
Each item is marked `VERIFY` in the code. Fix only what fails.
1. **Compile and run.** The sketch should compile for the UNO Q; start the app.
2. **Bridge and web page.** Open `http://<board-ip>:7000`. "Raw sensor readings" (in the Log card) should
   update every 2 s. Press a page button (e.g. "Low battery") and check the state changes: this proves the
   POST body reaches `api_action(payload)` in `main.py`.
3. **Analog range.** Turn the knob end to end. If the raw `a0` tops out near 4095 instead of 1023, set
   `ADC_MAX = 4095` and scale the `*_RAW` constants in `config.py`.
4. **Calibration.** Note raw values: knob at both ends, soil probe in air and in a damp tissue, light covered
   and uncovered, steam sensor dry and with a wet fingertip. Put them in `config.py` (`KNOB_*`, `SOIL_*`,
   `LIGHT_*`, `STEAM_WET_RAW`).
5. **Button.** Pressing the yellow button should start a photo check + decision once per press. If it fires
   on release instead, set `BUTTON_PRESSED = LOW` in the sketch.
6. **Relay.** Press "Force: water zone 1 for 10 min": the relay should click for 60 s, and a second press
   should be refused (4 h minimum). If it never clicks, the 3.3 V signal may not switch the 5 V relay module.
7. **Gemma.** The footer shows which model and URL the app uses. If decisions say "Gemma is off" or time
   out, check that the LLM brick serves the model named `LLM_MODEL` in `config.py` (the speed test in the
   repo's `spike/` folder can install it with `INSTALL_FOR_APPLAB=1`). Plan B: run `llama-server` by hand
   (see `spike/run_spike.sh`) and set `LLM_BASE_URL`.
8. **Unplugged sensors.** Remove each module that isn't wired from `CONNECTED` in `python/sensors.py`,
   otherwise its floating pin reads noise.

## If the Bridge stops answering
Community tip: in the board's terminal run `arduino-app-cli system cleanup` and `docker network prune`,
then start the app again.

## Tests
The Python side has tests that run on any computer: `python3 -m pytest tests` in the repository's
`app/garden-steward/` folder (the tests folder is not part of the App Lab zip).
