"""All the knobs of the Garden Steward in one place."""

import os

# The paper garden: zone number -> plant and the soil moisture range it likes (%).
ZONES = {
    1: {"plant": "tomatoes", "target": (35, 60)},
    2: {"plant": "lettuce", "target": (45, 70)},
}

# Simulated time runs fast: 1 real second = 1 simulated minute,
# so 1 real minute = 1 simulated hour and a full day takes 24 minutes.
# The sketch uses the same number (TIME_SCALE in sketch.ino). Use 1 for a real garden.
TIME_SCALE = 60

# How often Gemma looks at the garden (simulated hours).
DECIDE_EVERY_H = 2
# Below this soil moisture (%) Gemma is asked right away, and the fallback rule waters.
URGENT_SOIL = 25
FALLBACK_WATER_S = 20

# Safety limits. The microcontroller enforces these (sketch.ino); FakeMcu copies them.
MAX_PUMP_S = 60
MIN_INTERVAL_H = 4
MAX_PER_DAY = 3
BATTERY_FLOOR = 20

# Where Gemma 4 runs: a llama.cpp server with an OpenAI-style API.
# On the board, App Lab's LLM brick starts it as "llamacpp-models-runner" on port 9999.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://llamacpp-models-runner:9999/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-E2B_q4_0-it")
LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S", "300"))

# Where the decision log is written (one JSON object per line).
LOG_PATH = os.getenv("LOG_PATH", "garden_log.jsonl")
