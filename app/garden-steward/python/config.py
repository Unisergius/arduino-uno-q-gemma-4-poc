"""All the knobs of the Garden Steward in one place."""

import os

# The paper garden: zone number -> plant and the soil moisture range it likes (%).
ZONES = {
    1: {"plant": "tomatoes", "target": (35, 60)},
    2: {"plant": "lettuce", "target": (45, 70)},
}

# Wiring (DFRobot Gravity kit). The sketch uses the same pins - see the table in README.md.
# The UNO Q is 3.3 V logic: A0/A1 are NOT 5 V tolerant. D3 is not used.
PINS = {
    "A0": "Analog Rotation Sensor (knob) - zone 1 soil dial, VCC 3.3 V",
    "A1": "Soil Moisture Sensor SEN0114 - zone 2 soil probe, VCC 3.3 V",
    "A2": "LM35 temperature DFR0023 - VCC 5 V ok (output ~0.25 V)",
    "A3": "Ambient Light Sensor - VCC 3.3 V",
    "A4": "Steam Sensor - 'raining now' (wet fingertip), VCC 3.3 V",
    "D2": "Push button (yellow) - 'check now': photo + decide",
    "D4": "Relay Module DFR0017 - the 'pump', VCC 5 V",
    "D5": "Blue LED module - water flowing (optional)",
    "D6": "Red LED module - alert (optional)",
}

# Which kit modules are actually wired to the board. An unwired analog pin reads random noise, so a
# module only counts once you add it here. Empty = nothing wired: the simulation and the web page's
# buttons (Dry zone, Heatwave, Rain coming, Check now) stand in for every sensor - the demo still works.
# The relay (D4), the button (D2) and the LED matrix need no entry. Laptop mode's test bench uses all five.
SENSOR_ORDER = ("knob", "soil", "temp", "light", "steam")  # on pins A0..A4
ALL_SENSORS = set(SENSOR_ORDER)
WIRED_SENSORS = set()  # e.g. {"knob", "steam"}

# Turning raw analog readings (0..ADC_MAX) into numbers. Calibrate with the
# "Raw sensor readings" box on the web page: note the value dry and wet, put it here.
ADC_MAX = 1023        # measured on the UNO Q: analogRead() is 10-bit (the knob tops out at 1023)
ADC_VREF = 3.3        # volts at ADC_MAX
KNOB_DRY_RAW = 0      # knob turned fully one way = 0 % soil moisture
KNOB_WET_RAW = 1023   # ... fully the other way = 100 %
SOIL_DRY_RAW = 0      # SEN0114 in air
SOIL_WET_RAW = 700    # SEN0114 in water / a soaked tissue (VERIFY on your probe)
LIGHT_DARK_RAW = 0
LIGHT_BRIGHT_RAW = 800
STEAM_WET_RAW = 300   # above this the steam sensor counts as "raining now" (VERIFY)
TEMP_PLAUSIBLE = (-5, 50)  # °C; outside this the LM35 is ignored (unplugged / noise)

# No real water flows in the paper garden, so an accepted watering adds a
# pretend "watering bonus" to the soil reading, fading away over a few hours.
WATERING_BONUS = 25        # points of moisture per accepted watering (for a 30 s drink)
BONUS_FADE_H = 6           # simulated hours until a bonus has faded completely
RAIN_BONUS_PER_H = 6       # rain (real or simulated) adds this much per hour

# Simulated time runs fast: 1 real second = 1 simulated minute,
# so 1 real minute = 1 simulated hour and a full day takes 24 minutes.
# The sketch uses the same number (TIME_SCALE in sketch.ino). Use 1 for a real garden.
TIME_SCALE = 60

# How often Gemma looks at the garden (simulated hours). On the UNO Q one decision takes 2-3 real
# minutes, so with 1 real minute = 1 simulated hour this leaves Gemma some breathing room.
# The web page can pause automatic decisions (for a live demo: decide only when you press a button).
DECIDE_EVERY_H = 4
AUTO_DECIDE = os.getenv("AUTO_DECIDE", "1") != "0"
# Below this soil moisture (%) Gemma is asked right away, and the fallback rule waters.
URGENT_SOIL = 25
FALLBACK_WATER_S = 20

# Safety limits. The microcontroller enforces these (sketch.ino); FakeMcu copies them.
MAX_PUMP_S = 60
MIN_INTERVAL_H = 4
MAX_PER_DAY = 3
BATTERY_FLOOR = 20

# Where Gemma 4 runs: a llama.cpp server with an OpenAI-style API.
# "auto" looks for it: our own server on the board (spike/serve_gemma.sh, port 8080), seen directly or
# from inside App Lab's container, then App Lab's LLM brick. Set a URL to skip the search.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "auto")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-E2B_q4_0-it")  # any installed Gemma 4 is found by itself
LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S", "420"))     # a photo check can take minutes on the board

# Optional: a Seeed reCamera's video stream. Empty = no camera (the normal case now):
# "Check now" and the yellow button then use the test drawing picked on the web page,
# and you can always take a real photo of the paper garden with your phone on the web page.
# VERIFY the path on a reCamera (its web page / Node-RED on port 1880 shows the RTSP settings).
RECAMERA_URL = os.getenv("RECAMERA_URL", "")  # e.g. "rtsp://192.168.1.60:554/live"

# Built-in test drawings of the paper garden (assets/test-photos/<name>.png), for testing without a camera.
TEST_PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "test-photos")
TEST_PHOTOS = ("healthy", "sick")

# Where the decision log is written (one JSON object per line).
LOG_PATH = os.getenv("LOG_PATH", "garden_log.jsonl")
