"""Turn the MCU's raw analog readings into garden numbers, using the calibration in config.py.

The sketch sends raw values: {"a0": 512, "a1": 300, "a2": 70, "a3": 600, "a4": 20, "button": 3, ...}.
A sensor that isn't plugged in (or isn't listed in CONNECTED) comes back as None,
and the simulation fills in for it.
"""

import config

# Remove a name here if that module isn't wired up - floating pins read random noise.
CONNECTED = {"knob", "soil", "temp", "light", "steam"}


def to_percent(raw, low, high):
    if raw is None:
        return None
    return round(max(0.0, min(100.0, (raw - low) / (high - low) * 100)), 1)


def convert(raw, connected=CONNECTED):
    if not raw:
        return {}
    a = {pin: raw.get(pin) for pin in ("a0", "a1", "a2", "a3", "a4")}

    temp = None
    if "temp" in connected and a["a2"] is not None:
        volts = a["a2"] / config.ADC_MAX * config.ADC_VREF
        low, high = config.TEMP_PLAUSIBLE
        if low <= volts * 100 <= high:  # LM35: 10 mV per °C
            temp = round(volts * 100, 1)

    return {
        "soil": {
            1: to_percent(a["a0"], config.KNOB_DRY_RAW, config.KNOB_WET_RAW) if "knob" in connected else None,
            2: to_percent(a["a1"], config.SOIL_DRY_RAW, config.SOIL_WET_RAW) if "soil" in connected else None,
        },
        "temp_c": temp,
        "light": to_percent(a["a3"], config.LIGHT_DARK_RAW, config.LIGHT_BRIGHT_RAW) if "light" in connected else None,
        "raining": (a["a4"] > config.STEAM_WET_RAW) if "steam" in connected and a["a4"] is not None else None,
        "button": raw.get("button", 0),
    }
