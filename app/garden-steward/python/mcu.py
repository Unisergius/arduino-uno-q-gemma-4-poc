"""Talking to the microcontroller (MCU).

BridgeMcu talks to the real STM32 sketch over the UNO Q Bridge.
FakeMcu is a pure-Python stand-in with the same safety rules, so the whole app
can run on a laptop. The safety rules below must match sketch.ino.
"""

import json

import config


class SafetyRules:
    """'Gemma proposes, the MCU disposes': limits no AI answer can get past."""

    def __init__(self):
        self.waterings = {}  # zone -> list of sim hours

    def check(self, zone, seconds, now_h, battery, tank_empty, zones=config.ZONES):
        """Return (ok, seconds_to_run, note)."""
        if zone not in zones:
            return False, 0, f"unknown zone {zone}"
        if seconds <= 0:
            return False, 0, "nothing to do (0 s)"
        if tank_empty:
            return False, 0, "water tank is empty"
        if battery < config.BATTERY_FLOOR:
            return False, 0, f"battery {battery} % is below {config.BATTERY_FLOOR} %"
        times = [t for t in self.waterings.get(zone, []) if now_h - t < 24]
        if times and now_h - times[-1] < config.MIN_INTERVAL_H:
            return False, 0, f"watered {now_h - times[-1]:.1f} h ago, minimum is {config.MIN_INTERVAL_H} h"
        if len(times) >= config.MAX_PER_DAY:
            return False, 0, f"already watered {len(times)} times in 24 h"
        note = ""
        if seconds > config.MAX_PUMP_S:
            note = f"clamped from {seconds} s to {config.MAX_PUMP_S} s"
            seconds = config.MAX_PUMP_S
        times.append(now_h)
        self.waterings[zone] = times
        return True, seconds, note


class FakeMcu:
    """Pretends to be the sketch: no sensors (everything is simulated) and an imaginary pump."""

    def __init__(self, clock):
        self.clock = clock
        self.rules = SafetyRules()
        self.battery = 100
        self.tank_empty = False
        self.icon = "ok"

    def read_sensors(self):
        return {}

    def set_sim_state(self, battery, tank_empty):
        self.battery, self.tank_empty = battery, tank_empty

    def water(self, zone, seconds):
        ok, run_s, note = self.rules.check(zone, seconds, self.clock.hours(), self.battery, self.tank_empty)
        if ok:
            self.icon = "water"
        return {"ok": ok, "zone": zone, "seconds": run_s, "note": note}

    def show(self, icon):
        self.icon = icon


class BridgeMcu:
    """The real thing: calls the functions the sketch registers with Bridge.provide_safe()."""

    def __init__(self, bridge):
        self.bridge = bridge  # arduino.app_utils.Bridge

    def _call(self, name, *args):
        return self.bridge.call(name, *args, timeout=5)

    def read_sensors(self):
        return json.loads(self._call("read_sensors"))

    def set_sim_state(self, battery, tank_empty):
        self._call("set_sim_state", int(battery), bool(tank_empty))

    def water(self, zone, seconds):
        return json.loads(self._call("water", int(zone), int(seconds)))

    def show(self, icon):
        self._call("show", icon)
