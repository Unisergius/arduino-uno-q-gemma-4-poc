"""The pretend garden: a fast clock, the weather scenarios and the soil model.

Only this file is fake. Everything that reads from it (stats, Gemma, the MCU
safety rules, the log) is the same code a real garden would use.
"""

import math
import time
from datetime import datetime, timedelta

import config

SCENARIOS = ("normal", "heatwave", "rain_coming")


class SimClock:
    """Simulated time that runs `scale` times faster than real time."""

    def __init__(self, scale=config.TIME_SCALE, start=datetime(2026, 6, 1, 6, 0), real_time=time.monotonic):
        self.scale = scale
        self.start = start
        self._real_time = real_time
        self._real_start = real_time()

    def now(self):
        return self.start + timedelta(seconds=(self._real_time() - self._real_start) * self.scale)

    def hours(self):
        """Simulated hours since the start - handy for intervals."""
        return (self.now() - self.start).total_seconds() / 3600


class PaperGarden:
    """Two zones of soil that dry with heat and sun and get wetter when watered."""

    def __init__(self, zones=config.ZONES):
        self.moisture = {zone: 50.0 for zone in zones}
        self.scenario = "normal"
        self.scenario_since_h = 0.0
        self.pressure = 1015.0
        self.battery = 80.0
        self.tank_empty = False
        self.raining = False

    # --- buttons on the web page ---------------------------------------------------

    def set_scenario(self, name, now_h):
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}")
        self.scenario = name
        self.scenario_since_h = now_h
        self.raining = False

    def dry_out(self, zone):
        self.moisture[zone] = 20.0

    # --- physics (very rough, good enough for a demo) ----------------------------

    def weather(self, at, real=None):
        """Temperature, humidity and light for this moment.

        If a real sensor is plugged in and the scenario is "normal", its readings win.
        """
        hour = at.hour + at.minute / 60
        daylight = max(0.0, math.sin(math.pi * (hour - 6) / 14)) if 6 <= hour <= 20 else 0.0
        temp = 14 + 10 * daylight
        humidity = 70 - 25 * daylight
        if self.scenario == "heatwave":
            temp += 12
            humidity -= 20
        if self.scenario == "rain_coming":
            temp -= 3
            humidity += 15
            daylight *= 0.5
        weather = {"temp_c": round(temp, 1), "humidity": round(humidity), "light": round(100 * daylight)}
        if real and self.scenario == "normal":
            for key in ("temp_c", "humidity"):
                if real.get(key) is not None:
                    weather[key] = real[key]
        return weather

    def step(self, hours, at, now_h, real=None):
        """Move the garden forward by `hours` of simulated time."""
        w = self.weather(at, real)

        # Pressure falls before rain, otherwise drifts back to normal.
        if self.scenario == "rain_coming":
            self.pressure -= 1.5 * hours
            self.raining = now_h - self.scenario_since_h >= 4
        else:
            self.pressure += (1015.0 - self.pressure) * min(1.0, 0.3 * hours)
        if real and real.get("pressure_hpa") and self.scenario == "normal":
            self.pressure = real["pressure_hpa"]

        dry_per_hour = 0.8 + 0.08 * max(0.0, w["temp_c"] - 20) + 0.01 * w["light"]
        if self.scenario == "heatwave":
            dry_per_hour *= 2.5
        for zone in self.moisture:
            change = -dry_per_hour * hours
            if self.raining:
                change += 6 * hours
            self.moisture[zone] = min(100.0, max(0.0, self.moisture[zone] + change))

        # Solar battery: charges in the sun, drains at night.
        self.battery += (3 * w["light"] / 100 - 1) * hours
        self.battery = min(100.0, max(0.0, self.battery))
        return w

    def water(self, zone, seconds):
        """The (pretend) pump ran for `seconds`: about +0.6 % moisture per second."""
        self.moisture[zone] = min(100.0, self.moisture[zone] + 0.6 * seconds)

    def snapshot(self, at, real=None):
        w = self.weather(at, real)
        return {
            "moisture": {zone: round(m, 1) for zone, m in self.moisture.items()},
            "temp_c": w["temp_c"],
            "humidity": w["humidity"],
            "light": w["light"],
            "pressure_hpa": round(self.pressure, 1),
            "battery": round(self.battery),
            "tank_empty": self.tank_empty,
            "raining": self.raining,
            "scenario": self.scenario,
        }
