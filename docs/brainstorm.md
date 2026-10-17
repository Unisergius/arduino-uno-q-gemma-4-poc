# Brainstorm: an off-grid smart app on Arduino UNO Q + Gemma 4

Goal: a small proof of concept that shows what the UNO Q can do when it is paired
with Gemma 4, for a "smart" app that keeps working without mains power or a
reliable internet connection.

---

## 1. What we are working with

### Arduino UNO Q ("two brains" on one board)

| Part | What it is | What it is good for |
|---|---|---|
| **MPU** – Qualcomm Dragonwing QRB2210 | 4× Cortex‑A53 @ 2.0 GHz, Adreno GPU, Debian Linux, 2 GB/16 GB or 4 GB/32 GB | Python, Docker "Bricks", camera/mic, web UI, **running the LLM** |
| **MCU** – STM32U585 | Cortex‑M33, Arduino core on Zephyr | Real‑time sensors and actuators, timing, safety interlocks |
| **Bridge** | RPC between the sketch and the Linux side | Python calls `Bridge` functions in the sketch and the sketch calls back |
| On board | 8×13 LED matrix, Qwiic connector, UNO headers, Wi‑Fi, Bluetooth | Status display without a screen, plug-in sensors |
| **App Lab** | Combines a sketch, a Python app and Bricks (e.g. `keyword_spotting`, `video_object_detection`, `WebUI`) | Fast prototyping, Edge Impulse models |

### Gemma 4 (released April 2026, Apache 2.0)

| Model | Where it runs | Notes |
|---|---|---|
| **E2B** | On device (LiteRT‑LM, llama.cpp) | Text, image and audio input, function calling. ~1.5 GB peak RAM |
| **E4B** | On device | ~3 GB peak RAM, too big for the UNO Q in practice |
| **26B‑A4B** (MoE) / **31B** | **Gemini API (cloud)** – `gemma-4-26b-a4b-it`, `gemma-4-31b-it` | Thinking mode, function calling, image input, Search grounding |

### The key tension: "off-grid" vs the Gemini API

The page linked in the request (Gemma on the Gemini API) only covers the **cloud**
models. They need internet, which an off-grid device cannot count on. The page
itself is also marked as deprecated in favour of the new docs.

So the realistic architecture is **tiered, local-first and cloud-optional**:

```
Tier 0  MCU (STM32)      always on   sensors, actuators, hard safety limits, TinyML
Tier 1  Linux + E2B      on demand   local reasoning, vision, voice, function calls
Tier 2  Gemini API 26B   when online deeper analysis, weekly reports, "second opinion"
```

The device must be fully useful at Tier 0 + 1. Tier 2 is a bonus whenever a link
appears (phone hotspot, a trip into town, a satellite link, and so on).

### How fast will E2B be on the UNO Q? (unknown, must be measured)

Google's LiteRT‑LM numbers for **Raspberry Pi 5** (Cortex‑A76 @ 2.4 GHz) with E2B:
**~133 tok/s prefill, ~8 tok/s decode, ~1.5 GB peak RAM.**

The UNO Q uses older, in‑order Cortex‑A53 cores, so a rough estimate is
**~2–4 tok/s decode**. That estimate is unmeasured. Two consequences:

- Use the **4 GB UNO Q**. On the 2 GB board, E2B plus Debian plus App Lab will be very tight.
- Design for **short, structured outputs** (a function call or a JSON object), not chatty essays.
  A ~30 s "decision" every 15–30 min is fine. A conversational chatbot is not.

---

## 2. Design principles (apply to every idea below)

1. **Local-first, cloud-optional.** Everything important works offline.
2. **The LLM proposes, the MCU disposes.** Gemma *requests* actions through function calls
   (`water(zone, seconds)`). The STM32 firmware enforces hard limits such as maximum pump
   run time, minimum interval and battery cutoff, so the LLM can never override them.
3. **Don't make the LLM do maths.** Python computes the stats (min, max, trend, deltas).
   Gemma interprets them, decides between options and explains why in plain language.
4. **Event-driven inference.** Sleep most of the time and wake the model on a schedule or an
   event (threshold, PIR, keyword). This saves energy and hides the slow tokens/sec.
5. **Explainability as a feature.** Every action is logged with Gemma's one-line "why".
   This is where an LLM adds something a plain `if` statement can't.

---

## 3. Ideas

### Idea 1 – Garden / Greenhouse Steward 🌱 *(recommended)*

An off-grid plot or greenhouse that waters itself and explains its decisions.

- **MCU:** soil moisture, temperature/humidity, light and pressure sensors (Qwiic); controls
  the pump/valve relay; enforces the watering limits; shows status on the LED matrix
  (💧 watering, ☀️ OK, ⚠️ check me).
- **Gemma E2B:** every 30 min, reads a compact summary ("soil 31 %, falling 4 %/h, 29 °C,
  pressure dropping 3 hPa/3 h") and decides `water(zone, seconds)`, `wait()` or `alert(msg)`
  with a short reason ("rain likely, pressure dropping, skipping").
  A daily USB-camera photo goes through E2B's vision for wilting, yellowing or pests.
  Optional: a voice question through the `keyword_spotting` Brick ("Hey Arduino, how are the tomatoes?").
- **Cloud tier:** when online, send the week's log to Gemma 4 26B for a gardening report.
- **Extra hardware:** capacitive soil sensors, small 5 V/12 V pump with relay or MOSFET, USB webcam.
- **Why it's a good POC:** it uses *everything*. That covers MCU real-time control, the Bridge, the LED
  matrix, local LLM reasoning, function calling, vision, safety interlocks and optional cloud.
  Hardware is cheap and the demo is visual.

### Idea 2 – Off-grid Power Butler 🔋

A cabin/van/shed assistant that manages the solar system the board itself runs on.

- **MCU:** reads battery voltage/current (INA226 or similar), panel output, temperatures; reads a
  charge controller over UART (e.g. Victron VE.Direct); switches non-critical loads with relays.
- **Gemma E2B:** answers "Can I run the kettle tonight?" by calling `get_battery()`,
  `get_forecast_trend()` and `get_load_history()`. It plans load shedding ("fridge on, pump
  deferred until 11:00 when solar peaks") and explains low-battery events.
- **Cloud tier:** monthly energy report and sizing advice ("a second panel would cover 90 % of days").
- **Extra hardware:** current/voltage sensor, small panel and battery, relay module.
- **Why it's good:** it is the most genuinely *off-grid* idea, and function calling over real data is a
  great showcase. Weakness: less visual, and it needs a solar setup (it can be simulated at first).

### Idea 3 – Wildlife Field Station 🦊

A camera trap that writes a nature journal.

- **MCU:** PIR sensor wakes the system; the LED matrix shows the count of today's visitors.
- **Linux:** `video_object_detection` Brick filters empty frames; E2B describes each keeper
  ("young fox, left to right, 02:14").
  An Edge Impulse audio model detects bird calls.
- **Gemma E2B:** writes a daily journal entry from the events. It can be slow because it runs in a batch overnight.
- **Extra hardware:** USB webcam, PIR, optional USB mic.
- **Why it's good:** easy, fun, very visual. Weakness: the MCU is underused and it's more "smart" than "off-grid useful".

### Idea 4 – Mesh Messenger Copilot 📡

An LLM sidekick for a LoRa/Meshtastic off-grid mesh.

- **MCU:** talks to a LoRa radio module.
- **Gemma E2B:** summarises and triages incoming messages, translates them, and compresses outgoing
  status into the ~200 bytes a LoRa packet allows ("LLM as a compression codec").
- **Extra hardware:** LoRa module (+ a second node to talk to).
- **Why it's good:** real off-grid value. Weakness: highest complexity, and you need two nodes to demo.

### Idea 5 – Offline Field Manual 📖

Voice Q&A over offline manuals (water purification, radio procedures, equipment repair).

- **Gemma E2B:** answers from a small local document index and cites the page.
- **Why it's good:** shows the "knowledge without internet" angle. Weaknesses: barely uses the
  MCU or the board's I/O, and a 2B model **will** sometimes be confidently wrong. Never
  frame it as medical or safety advice. It should only show the relevant manual excerpt.

### Comparison

| | Uses UNO Q dual-brain | Shows off Gemma | Extra hardware | Difficulty | Off-grid value |
|---|---|---|---|---|---|
| 1 Garden Steward | **High** | **High** (reason + vision + tools) | Low | Medium | Medium |
| 2 Power Butler | **High** | Medium‑High (tools) | Low‑Med | Medium | **High** |
| 3 Wildlife Station | Medium | **High** (vision + narrative) | Low | Low‑Med | Low |
| 4 Mesh Copilot | Medium | Medium | Medium | **High** | **High** |
| 5 Field Manual | Low | Medium | Low | Medium | Medium |

Ideas 1 and 2 combine naturally into an **"Off-grid Homestead Hub"** later. The garden
module is a good first module and the power module a good second one.

---

## 4. Recommendation: start with the Garden Steward

### Phased plan

**Phase 0 – Feasibility spike (go/no-go, ~1 evening)**
- Run Gemma 4 E2B on the UNO Q: try llama.cpp (GGUF Q4) and LiteRT‑LM.
- Measure: prefill tok/s, decode tok/s, peak RAM, watts at idle and under load.
- Test one function-calling prompt end to end.
- **If too slow or too big:** fall back to a smaller Gemma (e.g. Gemma 3 1B or 270M) for local
  decisions and use Gemma 4 only through the cloud tier. Or consider the Arduino VENTUNO Q
  (Dragonwing IQ8, NPU, 16 GB) as an upgrade path.

**Phase 1 – MCU + Bridge**
- Sketch: read sensors, drive the relay, LED matrix states, hard safety limits.
- Expose `read_sensors()` / `water(zone, s)` over the Bridge, and test them from Python.

**Phase 2 – The brain**
- Python: rolling history plus a stats summary, then the Gemma prompt and function calls, then the Bridge.
- Decision log with reasons (JSON lines) plus a tiny `WebUI` Brick page.

**Phase 3 – Senses**
- Daily leaf photo through E2B vision.
- "Hey Arduino" voice query through `keyword_spotting`.

**Phase 4 – Cloud tier**
- When connectivity is detected, send the weekly log to `gemma-4-26b-a4b-it` and store the report locally.

### Success criteria for the POC
- Runs 48 h unattended with **no network**, making watering decisions with readable reasons.
- The MCU safety limits hold even if the LLM output is garbage (test this on purpose).
- Measured numbers recorded: tok/s, RAM, average power.

---

## 5. Open questions

1. Which UNO Q do you have, **2 GB or 4 GB**? This decides whether local E2B is realistic.
2. What does "off-grid" mean for you: **never online**, or **occasionally online**?
3. Which idea excites you most? Or is there a real place (garden, cabin, van, shed) you'd deploy it?
4. Power: will it run from **solar + battery**? If so, measured power draw becomes a Phase 0 must.

---

## Sources
- Gemma on the Gemini API: https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- Gemma 4 on LiteRT‑LM (benchmarks incl. Raspberry Pi 5): https://developers.google.com/edge/litert-lm/models/gemma-4
- Gemma 4 overview (sizes, modalities): https://simonwillison.net/b/9404 and https://www.mindstudio.ai/blog/gemma-4-e2b-e4b-edge-models-phone-local
- UNO Q specs and variants: https://www.macnica.co.jp/en/business/semiconductor/manufacturers/arduino/products/149785/index.html and https://store-usa.arduino.cc/products/uno-q
- App Lab Bricks: https://www.rs-online.com/designspark/what-is-arduino-app-lab-and-what-does-it-mean-for-engineers and https://docs.edgeimpulse.com/hardware/deployments/run-arduino-app-lab
- UNO Q power draw discussion: https://forum.arduino.cc/t/what-is-the-power-consumption-of-the-arduino-uno-q/1408753
- VENTUNO Q: https://www.cnx-software.com/2026/08/25/299-arduino-ventuno-q-sbc-combines-qualcomm-dragonwing-iq8-soc-and-stm32h5-mcu/
