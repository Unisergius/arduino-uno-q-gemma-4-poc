"""Turn raw readings into the few numbers Gemma needs. Gemma never does the maths."""

from collections import deque

import config


class History:
    """Recent snapshots, one every few simulated minutes."""

    def __init__(self, keep_hours=26):
        self.keep_hours = keep_hours
        self.points = deque()  # (sim hours, snapshot)
        self.last_watered_h = {}  # zone -> sim hours

    def add(self, now_h, snapshot):
        self.points.append((now_h, snapshot))
        while self.points and now_h - self.points[0][0] > self.keep_hours:
            self.points.popleft()

    def watered(self, zone, now_h):
        self.last_watered_h[zone] = now_h

    def value_hours_ago(self, hours, now_h, pick):
        """The reading closest to `hours` ago (or the oldest one we have)."""
        target = now_h - hours
        best = None
        for h, snap in self.points:
            if h <= target or best is None:
                best = (h, pick(snap))
            if h > target:
                break
        return best


def summarise(history, now_h, now_dt, zones=config.ZONES):
    """The numbers for one decision: levels, trends per hour and pressure change."""
    _, latest = history.points[-1]
    summary = {
        "time": now_dt.strftime("%H:%M"),
        "zones": {},
        "temp_c": latest["temp_c"],
        "humidity": latest["humidity"],
        "light": latest["light"],
        "pressure_hpa": latest["pressure_hpa"],
        "pressure_change_3h": 0.0,
        "battery": latest["battery"],
        "tank_empty": latest["tank_empty"],
        "raining": latest.get("raining", False),
    }

    old = history.value_hours_ago(3, now_h, lambda s: s["pressure_hpa"])
    if old:
        summary["pressure_change_3h"] = round(latest["pressure_hpa"] - old[1], 1)

    for zone, info in zones.items():
        moisture = latest["moisture"][zone]
        trend = 0.0
        old = history.value_hours_ago(3, now_h, lambda s, z=zone: s["moisture"][z])
        if old and now_h - old[0] > 0.1:
            trend = (moisture - old[1]) / (now_h - old[0])
        last = history.last_watered_h.get(zone)
        summary["zones"][zone] = {
            "plant": info["plant"],
            "moisture": moisture,
            "target": info["target"],
            "trend_per_h": round(trend, 1),
            "hours_since_watered": None if last is None else round(now_h - last, 1),
        }
    return summary


def describe(summary):
    """The summary as the short text that goes into Gemma's prompt."""
    change = summary["pressure_change_3h"]
    hint = " (rain likely)" if change <= -3 else ""
    # Put the rain on every zone's line, so Gemma doesn't have to connect the dots.
    rain = "; it is raining now" if summary.get("raining") else "; rain likely in the next hours" if hint else ""
    lines = [f"Time {summary['time']}."]
    for zone, z in summary["zones"].items():
        low, high = z["target"]
        watered = "never watered yet" if z["hours_since_watered"] is None else f"last watered {z['hours_since_watered']} h ago"
        lines.append(
            f"Zone {zone} {z['plant']}: soil {z['moisture']} % = {_level(z['moisture'], low, high)} "
            f"(target {low}-{high} %), {_trend(z['trend_per_h'])}, {watered}{rain}."
        )
    lines.append(
        f"Air {summary['temp_c']} °C, humidity {summary['humidity']} %, sunlight {summary['light']} %. "
        f"Pressure {summary['pressure_hpa']} hPa, {change:+} hPa in 3 h{hint}."
    )
    if summary.get("raining"):
        lines.append("It is raining right now.")
    tank = "EMPTY" if summary["tank_empty"] else "ok"
    lines.append(f"Battery {summary['battery']} %. Water tank {tank}.")
    return "\n".join(lines)


def _level(moisture, low, high):
    """Python compares the numbers; Gemma reads the words (small models misread numbers)."""
    if moisture < config.URGENT_SOIL:
        return "VERY DRY"
    if moisture < low:
        return "below target"
    if moisture > high:
        return "above target"
    return "in target range"


def _trend(per_h):
    if per_h <= -3:
        return f"falling fast {abs(per_h)} %/h"
    if per_h <= -0.5:
        return f"falling slowly {abs(per_h)} %/h"
    if per_h >= 0.5:
        return f"rising {per_h} %/h"
    return "stable"
