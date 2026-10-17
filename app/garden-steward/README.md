# Garden Steward: the Paper Garden demo

An Arduino App Lab app for the **Arduino UNO Q (4 GB)**. **Gemma 4 E2B**, running on the board,
decides when to water a garden drawn on paper. The **microcontroller enforces the safety limits**.
No internet is needed while it runs.

- `sketch/`: the microcontroller (STM32) side: sensors, relay "pump", LEDs, LED matrix, **safety limits**.
- `python/`: the Linux side: simulated garden, Gemma's three jobs (Decide, See, Explain), log, web page.
- `assets/`: the web page you open on your phone.
- `tests/`: automatic checks (`python3 -m pytest tests`).

## 1. Wiring (DFRobot Gravity kit) – optional

**No cables? The demo works without any wiring.** The LED matrix shows the watering, and the web page's
buttons stand in for the sensors: Dry zone, Heatwave, Rain coming, Force, the test drawings + Check now.
Gemma and the safety limits are the real thing either way. Wire modules only if you have male-to-male
jumpers (the kit's cables end in female plugs, like the board's headers), and list them in `WIRED_SENSORS`.

![The 9 kit modules to use, with their pins and power](../../docs/images/kit-wiring.jpg)

The UNO Q is **3.3 V logic**. **A0/A1 are not 5 V tolerant**, and the analog inputs top out around 3.3 V,
so power those sensors from **3.3 V**. **Don't use D3.** Each Gravity module has 3 wires: signal, VCC (red), GND (black).

| Pin | Module | Role | VCC |
|---|---|---|---|
| A0 | Analog Rotation Sensor (blue knob) | Zone 1 "soil dial": turn it to dry or wet the tomatoes | 3.3 V |
| A1 | Soil Moisture Sensor SEN0114 (fork) | Zone 2 real moisture: put the fork in a damp tissue | 3.3 V |
| A2 | LM35 temperature DFR0023 | real temperature (pinch it for a "heatwave") | 5 V is ok (output only ~0.25 V) |
| A3 | Ambient Light Sensor | real light (cover it for "night") | 3.3 V |
| A4 | Steam Sensor | "raining now": touch it with a wet fingertip | 3.3 V |
| D2 | Push button (yellow) | "check now": a photo (test drawing or camera), then Gemma decides | 3.3 V |
| D4 | Relay Module DFR0017 | the "pump": it clicks | 5 V (VERIFY: does the 3.3 V signal switch it?) |
| D5 | Blue LED module (optional) | water flowing | 3.3 V |
| D6 | Red LED module (optional) | alert | 3.3 V |

### Connecting the kit's cables (breadboard + jumper wires)

The kit's cables end in a black **female** 3-hole plug, and the UNO Q's pins are female too, so they don't
fit together. The board also has only one 3.3 V pin and one 5 V pin for 9 modules. You need:
- a **breadboard** (half size is fine), to share 3.3 V, 5 V and GND, and
- **male-to-male jumper wires**: about 30 for all 9 modules, 16 for the 4 essential ones.

```
UNO Q 3.3V ──► breadboard rail A (+) ◄── red wires: knob, soil probe, light, rain, button, LEDs
UNO Q GND  ──► breadboard rail A (−) ◄── black wires
UNO Q 5V   ──► breadboard rail B (+) ◄── red wires: relay and temperature ONLY   (put tape on it: "5 V")
UNO Q GND  ──► breadboard rail B (−) ◄── black wires
Each module's green wire ──► its own pin on the UNO Q: A0, A1, A2, A3, A4, D2, D4, D5, D6
```

For each module: plug the white end into the module, push three jumpers into the holes of the black end,
then take **green → its pin**, **red → a + rail**, **black → a − rail**. Check the colours against the
little `+`, `−` and `A`/`D` marks printed next to the module's socket. **Before powering on**, check that
nothing from the 5 V rail reaches A0–A5.

**Short on jumpers?** Wire the four that carry the demo first: **knob (A0)**, **relay (D4)**,
**yellow button (D2)** and **rain (A4)**. Then add temperature, soil probe, light and the LEDs.

**Tell the app what you wired:** tick it in the web page's **"Sensors wired to the board"** card (or add the
names to `WIRED_SENSORS` in `python/config.py` to make it permanent). Nothing is ticked at first, because
unwired analog pins read random noise; anything not ticked is simulated.

**Just the soil probe** (the one real sensor worth wiring with few cables): signal → **A1**, red → **3.3V**,
black → **GND** (3 male pins needed; with the board unplugged). Tick "Soil probe (A1)". Zone 2 (lettuce) then
follows the probe: in a damp tissue it reads moist, pulled out it reads dry. In "Raw sensor readings" note `a1`
in air and in water and put them in `SOIL_DRY_RAW` / `SOIL_WET_RAW` (if `a1` goes past 1023, the board reads
12-bit: set `ADC_MAX = 4095`). The relay, the button (the sketch holds D2 low) and the LED matrix
need no entry.

**Calibrate** (2 minutes): open the web page, expand **"Raw sensor readings"**, and note the knob at both
ends and the soil probe dry and in the damp tissue. Put those numbers in `python/config.py`
(`KNOB_DRY_RAW`, `SOIL_WET_RAW`, …).

**No camera needed.** With `RECAMERA_URL` empty (the default), "Check now" and the yellow button show Gemma
the **test drawing** picked on the web page (`assets/test-photos/healthy.png` or `sick.png`), and the
**phone upload** takes a real photo of your paper garden. (Optional: a Seeed reCamera on the same Wi‑Fi,
`RECAMERA_URL = "rtsp://<reCamera-ip>:554/live"`, VERIFY the path on the device.)

## 2. What is real and what is pretend

| Real | Pretend (simulated) |
|---|---|
| Gemma 4 decisions, the MCU safety limits, the relay click, LEDs, matrix | no water flows: an accepted watering adds a **watering bonus** (+25 points for a 30 s drink) that fades over ~6 simulated hours |
| knob (zone 1), soil probe (zone 2), temperature, light, "raining now" | air pressure / forecast (the **Rain coming** button), humidity, battery, water tank |

**Time runs fast:** 1 real minute = 1 simulated hour. Gemma looks every 2 simulated hours (2 real
minutes), or sooner when a zone gets very dry.

## 3. Run it on the board

1. **Gemma 4:** run the speed test once (`bash spike/run_spike.sh`, see `spike/README.md`), then start
   Gemma 4 as its own server on the board: `bash spike/serve_gemma.sh` (again after every reboot).
   The app finds it by itself (`LLM_BASE_URL = "auto"`). It doesn't use App Lab's LLM brick: on the UNO Q
   that only offers Gemma 3 1B / Qwen, and its container and the root disk are too small for Gemma 4.
2. **Import the app into App Lab:** download
   [`dist/garden-steward-applab.zip`](https://github.com/Unisergius/arduino-uno-q-gemma-4-poc/raw/main/dist/garden-steward-applab.zip)
   and use App Lab's **import** to add it (the zip has `garden-steward/app.yaml` at the top, the layout App Lab expects).
   Without import: create a new app and copy in `app.yaml`, `sketch/`, `python/` and `assets/` by hand.
3. Press **Run**. App Lab compiles the sketch, starts the LLM brick, and starts the Python side.
4. On your phone (same Wi‑Fi), open `http://<UNO-Q-IP>:7000`.
5. **Live demo tip:** one decision takes about 2–3 minutes on the board. Press **⏸ Pause automatic
   decisions** before presenting, so Gemma only thinks when you press a button, and talk while it thinks.
6. **With App Lab's Agentic Mode** (App Lab 0.10+): open it and paste
   > Read AGENTS.md in this app first. Then run the app and go through its "First run on the board" checklist
   > with me one step at a time. Explain each error in plain words before changing code, and never change
   > the safety limits or suggest 5 V on the analog pins.

After changing files in this folder, rebuild the zip: `python3 tools/make_applab_zip.py` (a test checks it is up to date).

The sketch compiles for the UNO Q (`arduino:zephyr:unoq`). It was tested with arduino-cli, but not yet on a board.

## 4. Test environment: a laptop, no board, no camera

Rehearse the whole demo before you get the board. Python 3.10+ and nothing else:

```bash
cd app/garden-steward/python
python3 laptop.py --no-llm     # quickest: no Gemma, the simple fallback rule decides
python3 laptop.py              # with Gemma: needs llama-server running (below)
```
Open the address it prints, normally http://localhost:7000 (or `http://<laptop-ip>:7000` on your phone,
same Wi‑Fi). On a Mac, AirPlay Receiver often holds port 7000, so it moves to 7001 and says so.

- **Test bench card** (laptop only): sliders stand in for the **knob**, **soil probe**, **temperature**
  and **light** sensors, a checkbox for the **wet fingertip on the rain sensor**, and a button for the
  **yellow button**. They go through the same code as the real sensors, so the demo works the same way.
- **Test drawings:** click **healthy** or **sick** in the photo card. That is what the pretend camera
  "sees" when you press **Check now** or the yellow button.
- **The microcontroller** is a Python stand-in with the **same safety limits** (60 s cap, 4 h gap, 3 a day).
- `--no-bench` turns the sliders off: then the soil dries out by itself and you use the scenario buttons.

To run Gemma on a laptop:
1. Get llama.cpp: on a Mac `brew install llama.cpp`; otherwise download the build for your computer from
   https://github.com/ggml-org/llama.cpp/releases (Linux: `llama-<version>-bin-ubuntu-x64.tar.gz`).
2. Download the two model files (4.3 GB together) from https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf:
   `gemma-4-E2B_q4_0-it.gguf` and `gemma-4-E2B-it-mmproj.gguf`.
3. Start it, then start `python3 laptop.py` (without `--no-llm`) in a second terminal:
   `llama-server -m gemma-4-E2B_q4_0-it.gguf --mmproj gemma-4-E2B-it-mmproj.gguf --alias gemma-4-E2B_q4_0-it --reasoning off --reasoning-budget 0 --port 8080`

Tested on a 4-core laptop CPU: a decision takes ~8 s, a photo check ~12–14 s. Both test drawings were
judged correctly every time (healthy 3/3, sick 3/3).

## 5. Demo script (for the presentation)

No wiring needed; with sensors wired, the knob / wet fingertip / yellow button do the same as the buttons.
Before you start, press **⏸ Pause automatic decisions**: each Gemma answer takes 1.5–3 minutes on the board.

1. **Show** the paper garden (zone 1 tomatoes, zone 2 lettuce) and the web page on a phone.
2. **Press Dry zone 1** (and **Heatwave**), then **Ask Gemma to decide now**. Gemma decides to water: the
   board's LED matrix shows drops and the log shows Gemma's reason.
3. **Press Rain coming**, then ask Gemma again. It waits and says why.
4. **Try to overwater:** press **Force: water zone 1 for 10 min**. The MCU cuts it to 60 s; press it again and
   it refuses ("minimum is 4 h"). The MCU has the last word.
5. **Sick plant:** pick the **sick** test drawing (or photograph your own paper drawing with the phone) and
   press **Check now**. Gemma flags it. Tip: Gemma reads **colour** reliably, not drooping shapes, so colour
   sick leaves **yellow/brown** (a highlighter or marker; blue pen alone won't do).
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
