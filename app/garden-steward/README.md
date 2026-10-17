# Garden Steward: the Paper Garden demo

An Arduino App Lab app for the **Arduino UNO Q (4 GB)**. **Gemma 4 E2B**, running on the board,
decides when to water a garden drawn on paper. The **microcontroller enforces the safety limits**.
No internet is needed while it runs.

- `sketch/`: the microcontroller (STM32) side: sensors, relay "pump", LEDs, LED matrix, **safety limits**.
- `python/`: the Linux side: simulated garden, Gemma's three jobs (Decide, See, Explain), log, web page.
- `assets/`: the web page you open on your phone.
- `tests/`: automatic checks (`python3 -m pytest tests`).

## 1. Wiring (DFRobot Gravity kit)

The UNO Q is **3.3 V logic**. **A0/A1 are not 5 V tolerant**, and the analog inputs top out around 3.3 V,
so power those sensors from **3.3 V**. **Don't use D3.** Each Gravity module has 3 wires: signal, VCC (red), GND (black).

| Pin | Module | Role | VCC |
|---|---|---|---|
| A0 | Analog Rotation Sensor (blue knob) | Zone 1 "soil dial": turn it to dry or wet the tomatoes | 3.3 V |
| A1 | Soil Moisture Sensor SEN0114 (fork) | Zone 2 real moisture: put the fork in a damp tissue | 3.3 V |
| A2 | LM35 temperature DFR0023 | real temperature (pinch it for a "heatwave") | 5 V is ok (output only ~0.25 V) |
| A3 | Ambient Light Sensor | real light (cover it for "night") | 3.3 V |
| A4 | Steam Sensor | "raining now": touch it with a wet fingertip | 3.3 V |
| D2 | Push button (yellow) | "check now": the reCamera takes a photo, then Gemma decides | 3.3 V |
| D4 | Relay Module DFR0017 | the "pump": it clicks | 5 V (VERIFY: does the 3.3 V signal switch it?) |
| D5 | Blue LED module (optional) | water flowing | 3.3 V |
| D6 | Red LED module (optional) | alert | 3.3 V |

Not every module plugged in? Remove its name from `CONNECTED` in `python/sensors.py`, and the
simulation fills in for it. Floating pins read random noise.

**Calibrate** (2 minutes): open the web page, expand **"Raw sensor readings"**, and note the knob at both
ends and the soil probe dry and in the damp tissue. Put those numbers in `python/config.py`
(`KNOB_DRY_RAW`, `SOIL_WET_RAW`, …).

**Seeed reCamera:** connect it to the same Wi‑Fi, find its IP address, and set
`RECAMERA_URL = "rtsp://<reCamera-ip>:554/live"` in `python/config.py`. VERIFY the exact stream path in
the reCamera's own web page / Node‑RED (port 1880). With no camera set, use the phone upload on the web page.

## 2. What is real and what is pretend

| Real | Pretend (simulated) |
|---|---|
| Gemma 4 decisions, the MCU safety limits, the relay click, LEDs, matrix | no water flows: an accepted watering adds a **watering bonus** (+25 points for a 30 s drink) that fades over ~6 simulated hours |
| knob (zone 1), soil probe (zone 2), temperature, light, "raining now" | air pressure / forecast (the **Rain coming** button), humidity, battery, water tank |

**Time runs fast:** 1 real minute = 1 simulated hour. Gemma looks every 2 simulated hours (2 real
minutes), or sooner when a zone gets very dry.

## 3. Run it on the board

1. **Gemma model:** run the Phase 0 spike once (`spike/README.md`) with `INSTALL_FOR_APPLAB=1`.
   That copies Gemma 4 E2B to where App Lab's LLM brick finds it.
   (Arduino lists Gemma 4 E2B officially only for the VENTUNO Q. VERIFY that App Lab's runner serves it
   on the UNO Q. Plan B: start `llama-server` yourself as in the spike, and set `LLM_BASE_URL` in `python/config.py`.)
2. In **App Lab**, create a new app and copy in `app.yaml`, `sketch/`, `python/` and `assets/` from this folder.
3. Press **Run**. App Lab compiles the sketch, starts the LLM brick, and starts the Python side.
4. On your phone (same Wi‑Fi), open `http://<UNO-Q-IP>:7000`.

The sketch compiles for the UNO Q (`arduino:zephyr:unoq`). It was tested with arduino-cli, but not yet on a board.

## 4. Run it on a laptop (no board)

Everything simulated, same web page. Python 3.10+, no extra packages:

```bash
cd python
python3 laptop.py --no-llm                          # without Gemma: the simple fallback rule only
python3 laptop.py --llm-url http://localhost:8080/v1  # with Gemma via a local llama-server
```
Then open http://localhost:7000. To run Gemma on a laptop:
`llama-server -m gemma-4-E2B_q4_0-it.gguf --mmproj gemma-4-E2B-it-mmproj.gguf --alias gemma-4-E2B_q4_0-it --reasoning off --reasoning-budget 0 --port 8080`
(the model files: https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf).

## 5. Demo script (for the presentation)

1. **Show** the paper garden (zone 1 tomatoes, zone 2 lettuce) and the web page on a phone.
2. **Turn the zone 1 knob to dry** (and pinch the temperature sensor for a heatwave). Gemma decides to water.
   The relay clicks, the blue LED and the matrix show water, and the log shows Gemma's reason.
3. **Touch the steam sensor with a wet fingertip** (or press **Rain coming**). Gemma waits and says it is raining.
4. **Try to overwater:** ask "water zone 1 for 10 minutes" (or press **Force**). The MCU clamps it to 60 s,
   or refuses with "minimum is 4 h" if zone 1 was watered in the last 4 simulated hours. Either way, the MCU has the last word.
5. **Swap a drawing** for a **yellow/brown** plant and press the **yellow button**. The reCamera takes a photo
   and Gemma flags it. Tip: Gemma reads **colour** reliably; it does not notice drooping shapes.
6. **Ask** "How's the lettuce doing?" Gemma answers from the log.

## 6. How Gemma is used (short version)

- **Decide:** Python turns readings into a short report and does the comparisons itself ("soil 20 % =
  VERY DRY", "falling fast", "rain likely"). Gemma returns one action per zone as JSON with a reason. A JSON
  schema is enforced by llama.cpp, so the JSON is always well-formed.
- **See:** a photo goes to Gemma's vision part, which answers `{leaves, status, confidence}`.
- **Explain:** answers questions and writes the evening journal. If you ask it to water, it *requests*
  watering, and the MCU still decides.
- **Gemma never does the maths and never has the last word:** Python validates, the fallback rule covers
  timeouts, and the MCU enforces the limits.
