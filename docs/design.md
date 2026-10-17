# Garden Steward – design

> A solar-powered Arduino UNO Q watches a garden, decides when to water and explains why.
> It runs **fully offline**, with **Gemma 4 E2B running on the board itself**.

## Decisions so far

| Question | Answer | Consequence |
|---|---|---|
| Board | **UNO Q 4 GB** | Gemma 4 E2B *should* fit, but the llama.cpp file is 3.35 GB (+0.99 GB vision); Phase 0 checks it |
| Connectivity | **Never online** | No cloud and no Gemini API at runtime. Everything is local |
| Where | **Garden** (outdoor) | Weatherproof box, water tank, real sensors (later) |
| Power | **Solar + battery** | The power budget matters; measure it in Phase 0 |
| First demo | **"Paper Garden"** | No water: soil and pump are simulated, garden drawn on paper |

---

## 1. The big picture

```
                     ┌─────────────────────── Arduino UNO Q (4 GB) ───────────────────────┐
  soil, temp,        │                                                                    │
  pressure, light ──►│  MCU  (STM32U585)                 Linux  (Qualcomm QRB2210)        │
                     │  • reads sensors every few s      • garden app (Python)            │
  pump / valve   ◄───│  • drives pump relay        Bridge• Gemma 4 E2B (llama.cpp)        │
                     │  • SAFETY LIMITS          ◄──RPC──► • decision log                 │
  LED matrix     ◄───│  • LED matrix status              • local web page                 │
                     └────────────────────────────────────────────────▲───────────────────┘
                                                                      │ the board's own Wi-Fi
  solar panel ─► charge controller ─► battery ─► 5 V USB-C ─► board   │ (no internet)
                                                                   📱 your phone
```

- **MCU (the "reflexes"):** real-time, always on, cheap on power. It owns everything physical
  and the hard safety rules.
- **Linux side (the "brain"):** runs the garden app and Gemma 4. It thinks occasionally.
- **Bridge:** the built-in RPC link. Python calls `water(zone, seconds)` and the sketch runs it.
- **Your phone:** connects to the board's own Wi-Fi hotspot (no internet) to see the log and ask questions.

## 2. One decision, step by step

1. **Sense.** The MCU reads the sensors every few seconds.
2. **Summarise.** Every 2 h (or when soil crosses a threshold), Python asks the MCU for readings over the
   Bridge and computes the numbers: trend per hour, pressure change over 3 h, hours since last watering.
3. **Prompt.** Python builds a short prompt: the garden profile, the summary and the list of allowed actions.
4. **Think.** **Gemma 4 E2B** answers with one action as JSON and a one-line reason.
5. **Check (software).** Python validates the JSON (known action, numbers in range).
6. **Check (hardware).** Python calls the MCU. The MCU applies its **hard limits** and runs the pump or refuses.
7. **Show.** The log, LED matrix and web page are updated with the action and Gemma's reason.

If Gemma times out or returns nonsense, a simple **fallback rule** takes over
("water 20 s if soil < 25 %"). The garden never depends on the AI being right.

## 3. How Gemma 4 is used

Gemma 4 **E2B** is the smallest Gemma 4 model. It takes text, images and audio, supports
function calling, is open (Apache 2.0) and is small enough to run on the UNO Q with no internet.
It runs inside **llama.cpp** on the Linux side. LiteRT‑LM is the alternative; Phase 0 picks the faster one.

Gemma has **three jobs**:

| Job | When | Input | Output |
|---|---|---|---|
| **Decide** | every ~2 h + on threshold | text summary of sensors | one action: `water` / `wait` / `alert` + reason |
| **See** | once a day (or on demand) | a photo of the plants | `{status, issue, confidence}` |
| **Explain** | evening + when you ask | the day's log, or your question | a short journal entry / answer |

### Example: "Decide"

What Python sends (built from sensor numbers):

```
Time 07:10. Zone 1 tomatoes: soil 28 % (target 35-60 %), falling 3 %/h.
Zone 2 lettuce: soil 52 %, stable.
Air 27 °C, humidity 40 %. Pressure 1006 hPa, down 4 hPa in 3 h.
Battery 78 %. Zone 1 last watered 22 h ago.
```

What Gemma answers. The JSON shape is enforced by llama.cpp's grammar‑constrained decoding,
so the model *cannot* produce broken JSON:

```json
{"action": "water", "zone": 1, "seconds": 30,
 "reason": "Tomatoes below target and drying fast; rain not certain, short drink."}
```

### What Gemma does **not** do
- **Maths:** Python computes trends and averages; Gemma interprets them.
- **Safety:** the MCU enforces limits Gemma can't override.
- **Timing / control loops:** the MCU handles real time.

### Why Gemma 4 (and not a bigger cloud model)
- **Offline:** open weights running on the board. No internet, no API key, no subscription.
- **Small enough (to be confirmed):** built for phones (~1.5 GB peak on a Raspberry Pi 5 with LiteRT‑LM). The llama.cpp file is 3.35 GB, so fitting the 4 GB board is Phase 0's first question. Smaller 2.4–2.5 GB versions exist.
- **One model, many senses:** text, vision and audio in one model, so no separate image model is needed.
- **Function calling:** made for "pick an action" tasks.
- **Same family scales up:** the 26B/31B models are there if it ever goes online.

## 4. Safety: "Gemma proposes, the microcontroller disposes"

Enforced in the MCU sketch. The same rules apply in the simulation:

| Rule | Value (default) |
|---|---|
| Max pump run per watering | 60 s |
| Min time between waterings, per zone | 4 h (sim: 4 simulated hours) |
| Max waterings per zone per day | 3 |
| No watering if battery below | 20 % |
| No watering if tank empty | float switch (real) / simulated flag |

If Gemma (or the web page's **Force** button) asks for "water zone 1 for 10 minutes", the MCU caps it at 60 s.
Asking again within 4 simulated hours is refused outright. The demo shows this on purpose.

## 5. The "Paper Garden" simulation (first demo)

No water and no plants needed. **The brain is real; only the garden is pretended.**

| Part | Real garden (later) | Paper Garden (now) |
|---|---|---|
| Soil moisture | capacitive soil sensors | Zone 1: **a knob** you turn to "dry" the soil. Zone 2: **a real soil probe** in a damp tissue. Both get a simulated "watering bonus" when the MCU accepts a watering |
| Pump | 12 V pump via relay/MOSFET | **relay click** + water-drop animation on the LED matrix |
| Weather | temp/humidity/pressure sensor | **real** temperature (LM35), light and rain (steam sensor) readings; the pressure forecast comes from **scenario buttons** (Normal, Heatwave, Rain coming) |
| Plants | real plants + camera | **drawings on paper**, photographed by the **Seeed reCamera** (phone upload as fallback) |
| Battery / solar | solar panel + LiFePO4 | simulated battery level |
| Gemma, Bridge, safety rules, log, web page | ✅ real | ✅ **real – identical code** |

**Time runs fast:** 1 real minute = 1 simulated hour, so a full day takes ~24 minutes.

### Demo script (for the presentation)
1. **Show the paper garden** (e.g. Zone 1 tomatoes, Zone 2 lettuce) and the web page on a phone.
2. **Turn zone 1's soil knob down** (and pinch the temperature sensor for a heatwave). Gemma decides to
   water. The relay clicks, the matrix shows drops and the log shows the reason.
3. **Touch the rain sensor with a wet fingertip** (or press "Rain coming"). Gemma skips watering and says why.
4. **Try to overwater it:** ask "water zone 1 for 10 minutes". The **MCU refuses** with a safety limit.
5. **Swap a drawing:** a green plant becomes a yellow, drooping one. Press the yellow button; the reCamera
   takes a photo and Gemma flags it.
6. **Ask a question:** "How's the lettuce doing?" Gemma answers from the log.

## 6. Power budget (real deployment – estimates, to be measured in Phase 0)

| Consumer | Assumption | Per day |
|---|---|---|
| UNO Q always on (+ sensors) | ~2 W average (unmeasured; ~1 W idle is reported) | ~48 Wh |
| Gemma thinking | 12 decisions × 60 s × ~5 W (guess) | ~1 Wh |
| Pump | 12 V × 1 A × 2 min | ~0.4 Wh |
| **Total** | | **~50 Wh/day** |

**Key insight:** the AI is *not* the energy problem (~2 %). Keeping Linux awake is.

Rough sizing: **3 days without sun** ≈ 150 Wh usable, so a **12 V 20 Ah LiFePO4** (~256 Wh)
plus a **30–50 W panel** and an MPPT charge controller.

### Wiring: your parts (DFRobot Gravity kit KIT0011 + Seeed reCamera)

The UNO Q's pins are **3.3 V logic**. A0/A1 are **not** 5 V tolerant, analog inputs top out around 3.3 V, and D3 is avoided.
Each Gravity module has 3 wires: **signal**, **VCC** (red), **GND** (black).

| Pin | Module | Role in the Paper Garden | Power |
|---|---|---|---|
| A0 | Analog Rotation Sensor (blue knob) | Zone 1 "soil dial" | 3.3 V |
| A1 | Soil Moisture Sensor (fork probe) | Zone 2 real moisture (probe in a damp tissue) | 3.3 V |
| A2 | LM35 temperature sensor | real temperature (pinch it for a "heatwave") | 5 V (its output is only ~0.25 V, so it is safe) |
| A3 | Ambient Light Sensor | real light (cover it for "night") | 3.3 V |
| A4 | Steam Sensor | "raining now" (wet fingertip) | 3.3 V |
| D2 | Yellow push button | "check now": take a photo and decide | 3.3 V |
| D4 | Relay Module (DFR0017) | the "pump" (it clicks) | 5 V (to verify: the 3.3 V signal switches it) |
| D5 | Blue LED module (optional) | "water flowing" | 3.3 V |
| D6 | Red LED module (optional) | alert | 3.3 V |

**Seeed reCamera:** a separate camera with its own small Linux computer. It joins the same local Wi-Fi.
The Garden Steward grabs one frame from its video stream (`rtsp://<reCamera-ip>:554/live`, to verify on the device).
**Cables:** if the Gravity cables end in plugs that don't fit the UNO Q's female headers, use male-to-male
jumper wires or a DFRobot Gravity IO expansion shield.

## 7. Parts

**Paper Garden (what we have):** UNO Q 4 GB, USB‑C cables and power supply, the DFRobot Gravity
27‑piece sensor kit (see the wiring table above), a Seeed reCamera, paper and pens.
A USB webcam would need a USB‑C hub with power delivery (the UNO Q has a single USB‑C port), which is why the
reCamera over Wi‑Fi is the better fit.

**Real garden (later):** capacitive soil sensors (I²C/Qwiic), 12 V pump or valve + relay/MOSFET,
float switch for the tank, a **real-time clock module** (no internet means no clock sync),
battery monitor (INA226-type), solar panel, MPPT controller, LiFePO4 battery, 12 V→USB‑C PD
converter, IP65 box with cable glands.

## 8. Unknowns to settle in Phase 0

| Unknown | Why it matters | Plan B |
|---|---|---|
| E2B speed on UNO Q (est. 2–4 tok/s) | sets how often Gemma can think | shorter prompts, or Gemma 3 1B for "Decide" |
| E2B RAM with App Lab running | 3.35 GB model + 0.99 GB vision on 4 GB shared with Debian; App Lab's LLM container is capped at 2.5 GB | `VISION=0`, a 2.4–2.5 GB quantization, llama.cpp outside App Lab, or LiteRT‑LM |
| Arduino lists Gemma 4 E2B only for the VENTUNO Q | App Lab's LLM brick may not serve it on the UNO Q | run `llama-server` ourselves (`LLM_BASE_URL`) |
| Gemma 4 vision on the board | the "See" job (works in llama.cpp on a laptop: spots yellow/brown, not droopy shapes) | phone upload, or drop vision from the POC |
| Board as Wi-Fi hotspot | phone and reCamera without internet | the reCamera's own hotspot, or LED matrix only |
| Real power draw | solar sizing | bigger battery/panel |

## 9. Plan

| Phase | What | Done when |
|---|---|---|
| 0 – Spike | Gemma 4 E2B on the board, measure speed/RAM/power | one JSON decision in < 90 s |
| 1 – Paper Garden | simulated soil + real Gemma + MCU safety + web page | demo script runs end to end |
| 2 – Real sensors | swap simulated soil/weather for real sensors | readings match reality |
| 3 – Outdoors | solar, battery, box, water | 48 h unattended, offline |

## 10. What the first test run showed (laptop, not the board yet)

The real Gemma 4 E2B (`google/gemma-4-E2B-it-qat-q4_0-gguf`) in llama.cpp, with the real prompts:

- **Decision time:** ~8 s at ~16 tok/s on a 4-core x86 machine. The UNO Q will be slower.
- **Hidden thinking:** E2B started reasoning out loud in 6 of 12 replies even with thinking off. An empty
  assistant prefill plus a zero reasoning budget fixed it (12 of 12).
- **Numbers:** it misread "33 %" as "below 25 %". Python now labels each zone (VERY DRY / below target /
  in target range) and adds rain to every zone's line. It then followed the rules in 13 of 14 checks.
- **Vision:** it reliably flags yellow/brown drawings, not green drooping ones, so sick plants get coloured.

The code is in [`app/garden-steward/`](../app/garden-steward/README.md) and the Phase 0 test in [`spike/`](../spike/README.md).
