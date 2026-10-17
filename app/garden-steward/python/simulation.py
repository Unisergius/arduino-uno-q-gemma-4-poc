"""The pretend parts of the garden: a fast clock, the weather scenarios and the soil.

Real sensor readings win whenever they exist (knob, soil probe, LM35, light, steam).
Everything missing is simulated, so the same code runs on a laptop with no sensors.
No real water flows, so an accepted watering adds a "watering bonus" that fades away.
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
    def __init__(self, zones=config.ZONES):
        self.base = {zone: 50.0 for zone in zones}   # simulated soil, used when a zone has no sensor
        self.bonus = {zone: 0.0 for zone in zones}   # pretend water from waterings and rain
        self.scenario = "normal"
        self.scenario_since_h = 0.0
        self.pressure = 1015.0                       # always simulated: the "forecast"
        self.battery = 80.0                          # always simulated
        self.tank_empty = False
        self.sim_raining = False

    # --- buttons on the web page ---------------------------------------------------

    def set_scenario(self, name, now_h):
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}")
        self.scenario = name
        self.scenario_since_h = now_h
        self.sim_raining = False

    def dry_out(self, zone):
        """Only affects a zone without a sensor - on the board, turn the knob instead."""
        self.base[zone] = 20.0
        self.bonus[zone] = 0.0

    # --- readings: real when available, simulated otherwise ------------------------

    def weather(self, at, real):
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
        return {
            "temp_c": real.get("temp_c") if real.get("temp_c") is not None else round(temp, 1),
            "humidity": round(humidity),  # no humidity sensor in the kit: always simulated
            "light": real.get("light") if real.get("light") is not None else round(100 * daylight),
        }

    def raining(self, real):
        return bool(real.get("raining")) or self.sim_raining

    def soil(self, zone, real):
        sensor = real.get("soil", {}).get(zone)
        base = sensor if sensor is not None else self.base[zone]
        return min(100.0, base + self.bonus[zone])

    # --- physics (very rough, good enough for a demo) ----------------------------

    def step(self, hours, at, now_h, real=None):
        """Move the garden forward by `hours` of simulated time."""
        real = real or {}
        w = self.weather(at, real)

        # Pressure falls before rain, otherwise drifts back to normal. Rain starts 4 h after "Rain coming".
        if self.scenario == "rain_coming":
            self.pressure -= 1.5 * hours
            self.sim_raining = now_h - self.scenario_since_h >= 4
        else:
            self.pressure += (1015.0 - self.pressure) * min(1.0, 0.3 * hours)

        hot = 2.5 if self.scenario == "heatwave" or w["temp_c"] >= 30 else 1.0
        dry_per_hour = (0.8 + 0.08 * max(0.0, w["temp_c"] - 20) + 0.01 * w["light"]) * hot
        fade_per_hour = config.WATERING_BONUS / config.BONUS_FADE_H * hot
        raining = self.raining(real)
        for zone in self.base:
            self.base[zone] = max(0.0, self.base[zone] - dry_per_hour * hours)
            if raining:
                self.bonus[zone] = min(100.0, self.bonus[zone] + config.RAIN_BONUS_PER_H * hours)
            else:
                self.bonus[zone] = max(0.0, self.bonus[zone] - fade_per_hour * hours)

        # Solar battery: charges in the sun, drains at night.
        self.battery += (3 * w["light"] / 100 - 1) * hours
        self.battery = min(100.0, max(0.0, self.battery))

    def water(self, zone, seconds):
        """The MCU accepted a watering: a 30 s drink is worth WATERING_BONUS points."""
        self.bonus[zone] = min(100.0, self.bonus[zone] + config.WATERING_BONUS * seconds / 30)

    def snapshot(self, at, real=None):
        real = real or {}
        w = self.weather(at, real)
        soil = real.get("soil", {})
        return {
            "moisture": {zone: round(self.soil(zone, real), 1) for zone in self.base},
            "temp_c": w["temp_c"],
            "humidity": w["humidity"],
            "light": w["light"],
            "pressure_hpa": round(self.pressure, 1),
            "battery": round(self.battery),
            "tank_empty": self.tank_empty,
            "raining": self.raining(real),
            "scenario": self.scenario,
            # what is real and what is pretend - shown on the web page
            "sources": {
                "soil": {zone: "sensor" if soil.get(zone) is not None else "simulated" for zone in self.base},
                "temp": "sensor" if real.get("temp_c") is not None else "simulated",
                "light": "sensor" if real.get("light") is not None else "simulated",
                "rain": "sensor" if real.get("raining") is not None else "simulated",
            },
        }
