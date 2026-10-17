# Garden Steward – design

> A solar-powered Arduino UNO Q watches a garden, decides when to water and explains why.
> It runs **fully offline**, with **Gemma 4 E2B running on the board itself**.

## Decisions so far

| Question | Answer | Consequence |
|---|---|---|
| Board | **UNO Q 4 GB** | Gemma 4 E2B (~1.5 GB peak RAM) fits on the board |
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
- **Small enough:** E2B fits in the 4 GB board's memory.
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

If Gemma suggests "water zone 1 for 10 minutes", the MCU runs 60 s at most and logs the refusal.
The demo shows this on purpose.

## 5. The "Paper Garden" simulation (first demo)

No water and no plants needed. **The brain is real; only the garden is pretended.**

| Part | Real garden (later) | Paper Garden (now) |
|---|---|---|
| Soil moisture | capacitive soil sensors | **software soil model**: dries faster with heat and light, rises when watered |
| Pump | 12 V pump via relay/MOSFET | **relay click or LED** + water-drop animation on the LED matrix |
| Weather | temp/humidity/pressure sensor | real sensor if you have one, otherwise **scenario buttons**: Heatwave, Rain coming, Normal |
| Plants | real plants + webcam | **drawings on paper** + webcam *or a phone photo uploaded on the web page* |
| Battery / solar | solar panel + LiFePO4 | simulated battery level |
| Gemma, Bridge, safety rules, log, web page | ✅ real | ✅ **real – identical code** |

**Time runs fast:** 1 real minute = 1 simulated hour, so a full day takes ~24 minutes.

### Demo script (for the presentation)
1. **Show the paper garden** (e.g. Zone 1 tomatoes, Zone 2 lettuce) and the web page on a phone.
2. **Press "Heatwave".** Zone 1 dries over a few minutes. Gemma decides to water. The relay clicks,
   the matrix shows drops and the log shows the reason.
3. **Press "Rain coming"** (pressure falls). Gemma skips watering and says why.
4. **Try to overwater it:** ask "water zone 1 for 10 minutes". The **MCU refuses** with a safety limit.
5. **Swap a drawing:** a green plant becomes a yellow, drooping one. Take a photo and Gemma flags it.
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

## 7. Parts

**Paper Garden (minimum):** UNO Q 4 GB, a good USB‑C power supply, paper and pens.
**Nice to have:** a Qwiic temp/humidity/pressure sensor (real weather), a relay module or LED (the "pump"),
a knob/potentiometer (manually "dry" the soil), a USB webcam **plus a USB‑C hub with power delivery**
(the UNO Q has a single USB‑C port, and Arduino says a PD hub is required for cameras).

**Real garden (later):** capacitive soil sensors (I²C/Qwiic), 12 V pump or valve + relay/MOSFET,
float switch for the tank, a **real-time clock module** (no internet means no clock sync),
battery monitor (INA226-type), solar panel, MPPT controller, LiFePO4 battery, 12 V→USB‑C PD
converter, IP65 box with cable glands.

## 8. Unknowns to settle in Phase 0

| Unknown | Why it matters | Plan B |
|---|---|---|
| E2B speed on UNO Q (est. 2–4 tok/s) | sets how often Gemma can think | shorter prompts, or Gemma 3 1B for "Decide" |
| E2B RAM with App Lab running | 4 GB shared with Debian + containers | run llama.cpp outside Docker, smaller quant |
| Gemma 4 vision in llama.cpp | the "See" job | LiteRT‑LM, or drop vision from the POC |
| Board as Wi-Fi hotspot | phone access without internet | USB/Ethernet via hub, or LED matrix only |
| Real power draw | solar sizing | bigger battery/panel |

## 9. Plan

| Phase | What | Done when |
|---|---|---|
| 0 – Spike | Gemma 4 E2B on the board, measure speed/RAM/power | one JSON decision in < 90 s |
| 1 – Paper Garden | simulated soil + real Gemma + MCU safety + web page | demo script runs end to end |
| 2 – Real sensors | swap simulated soil/weather for real sensors | readings match reality |
| 3 – Outdoors | solar, battery, box, water | 48 h unattended, offline |
