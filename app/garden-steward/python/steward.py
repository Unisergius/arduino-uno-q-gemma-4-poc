"""The Garden Steward: runs the garden clock, asks Gemma, acts through the MCU, keeps the log.

tick() is called about once a real second from the main loop.
Gemma jobs (decide / ask / photo / journal) run one at a time on a worker thread,
so a slow answer never blocks the garden or the web page.
"""

import json
import queue
import threading
import time
from collections import deque

import brain
import camera
import config
import sensors
from simulation import PaperGarden, SimClock
from stats import History, describe, summarise


class Steward:
    def __init__(self, mcu, llm, clock=None, garden=None, log_path=config.LOG_PATH, wired=None):
        self.mcu = mcu
        self.wired = set(config.WIRED_SENSORS if wired is None else wired)  # kit modules actually wired up
        self.llm = llm  # None = Gemma off, fallback rule only
        self.clock = clock or SimClock()
        self.garden = garden or PaperGarden()
        self.history = History()
        self.log_path = log_path
        self.log = deque(maxlen=200)
        self.jobs = queue.Queue()
        self.lock = threading.Lock()
        self.busy = None
        self.busy_since = 0.0
        self.icon = "ok"
        self.pump_until = 0.0
        self.answer = None
        self.photo = None
        self.auto_decide = config.AUTO_DECIDE  # off = Gemma decides only when asked (live demos)
        self.test_photo = config.TEST_PHOTOS[0]  # the drawing the pretend camera "sees" when there is no camera
        self.raw = {}   # raw readings from the MCU (for calibrating)
        self.real = {}  # the same, converted (see sensors.py); empty without sensors
        self.last_button = None
        self.sent_state = None
        self.last_tick_h = self.clock.hours()
        self.last_decision_h = None
        self.last_journal_day = None
        self.ticks = 0

    # --- the heartbeat -----------------------------------------------------------------

    def tick(self):
        now_h, now = self.clock.hours(), self.clock.now()
        self.raw = self._mcu("read_sensors") or {}
        self.real = sensors.convert(self.raw, self.wired)
        with self.lock:
            hours = now_h - self.last_tick_h
            self.last_tick_h = now_h
            if hours > 0:
                self.garden.step(hours, now, now_h, self.real)
            snap = self.garden.snapshot(now, self.real)
            self.history.add(now_h, snap)

        # The MCU enforces the battery floor and the empty tank, so keep it up to date.
        state = (int(snap["battery"]), snap["tank_empty"])
        if state != self.sent_state:
            self._mcu("set_sim_state", *state)
            self.sent_state = state
        self.ticks += 1

        # The yellow button: take a photo, then decide.
        presses = self.real.get("button")
        if presses is not None and self.last_button is not None and presses > self.last_button:
            self.check_now()
        if presses is not None:
            self.last_button = presses

        if self.auto_decide and self.busy is None and self.jobs.empty():
            since = None if self.last_decision_h is None else now_h - self.last_decision_h
            due = since is None or since >= config.DECIDE_EVERY_H
            urgent = min(snap["moisture"].values()) < config.URGENT_SOIL and (since is None or since >= 1)
            if due or urgent:
                self.last_decision_h = now_h
                self.jobs.put(("decide", None))
        if now.hour == 20 and self.last_journal_day != now.date():
            self.last_journal_day = now.date()
            self._enqueue("journal")

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            kind, payload = self.jobs.get()
            self.busy, self.busy_since = kind, time.monotonic()
            try:
                getattr(self, f"_job_{kind}")(payload)
            except Exception as error:
                self._write_log("error", job=kind, error=str(error))
            finally:
                self.busy = None

    def _waiting(self):
        """The kinds of job waiting in the queue (not the one running)."""
        with self.jobs.mutex:
            return [kind for kind, _ in self.jobs.queue]

    def _enqueue(self, kind):
        """Queue a Gemma job unless the same one is already waiting: on the board each takes minutes."""
        if kind not in self._waiting():
            self.jobs.put((kind, None))

    # --- Gemma jobs --------------------------------------------------------------------

    def _summary(self):
        with self.lock:
            now_h, now = self.clock.hours(), self.clock.now()
            self.history.add(now_h, self.garden.snapshot(now, self.real))  # fresh, not up to 1 s old
            summary = summarise(self.history, now_h, now)
        return summary, describe(summary)

    def _job_decide(self, _):
        summary, text = self._summary()
        self._show("think")
        if self.llm is None:
            result = {"decisions": brain.fallback(summary), "source": "fallback", "llm": None, "error": "Gemma is off"}
        else:
            result = brain.decide(summary, text, self.llm)
        icon = "ok"
        for d in result["decisions"]:
            if d["action"] == "water":
                self._wait_for_pump()  # one pump: the MCU refuses a second zone while the first is watering
            outcome = self._act(d["zone"], d["seconds"]) if d["action"] == "water" else None
            self._write_log("decision", zone=d["zone"], action=d["action"], seconds=d["seconds"],
                            reason=d["reason"], source=result["source"], mcu=outcome,
                            llm=result["llm"], error=result["error"], prompt=text)
            if d["action"] == "alert" or (outcome and not outcome["ok"]):
                icon = "alert"
        self._show(icon)

    def _job_ask(self, question):
        if self.llm is None:
            raise RuntimeError("Gemma is off")
        summary, text = self._summary()
        self._show("think")
        reply, info = brain.ask(question, text, self._recent_log(), self.llm)
        outcome = None
        if reply["water_zone"] and reply["water_seconds"]:
            outcome = self._act(reply["water_zone"], reply["water_seconds"])
        self.answer = {"question": question, "answer": reply["answer"], "mcu": outcome, "llm": info}
        self._write_log("ask", question=question, answer=reply["answer"], zone=reply["water_zone"] or None,
                        seconds=reply["water_seconds"], mcu=outcome, llm=info)
        self._show("ok" if not outcome or outcome["ok"] else "alert")

    def check_now(self):
        if self.busy == "snap" or "snap" in self._waiting():
            return  # already looking at the photo; pressing again would only queue minutes of work
        self.last_decision_h = self.clock.hours()
        self.jobs.put(("snap", None))
        self._enqueue("decide")

    def _job_snap(self, _):
        """Grab a frame from the reCamera - or, with no camera, use the test drawing picked on the web page."""
        self._show("think")
        if config.RECAMERA_URL:
            photo = {"image_b64": camera.grab_jpeg_b64(config.RECAMERA_URL), "mime": "image/jpeg"}
        else:
            photo = {"image_b64": camera.test_photo_b64(self.test_photo), "mime": "image/png",
                     "test_photo": self.test_photo}
        self._job_photo(photo)

    def _job_photo(self, payload):
        if self.llm is None:
            raise RuntimeError("Gemma is off")
        self._show("think")
        verdict, info = brain.check_photo(payload["image_b64"], self.llm, payload.get("mime", "image/jpeg"))
        self.photo = {**verdict, "llm": info}
        self._write_log("see", status=verdict["status"], issue=verdict["leaves"],
                        confidence=verdict["confidence"], test_photo=payload.get("test_photo"), llm=info)
        self._show("ok" if verdict["status"] == "healthy" else "alert")

    def _job_journal(self, _):
        if self.llm is None:
            raise RuntimeError("Gemma is off")
        _, text = self._summary()
        entry, info = brain.journal(text, self._recent_log(40), self.llm)
        self._write_log("journal", text=entry.strip(), llm=info)

    # --- talking to the MCU ------------------------------------------------------------

    def _act(self, zone, seconds):
        """Ask the MCU to water. It may clamp or refuse - its word is final."""
        outcome = self._mcu("water", int(zone), int(seconds))
        if outcome is None:
            return {"ok": False, "zone": zone, "seconds": 0, "note": "MCU did not answer"}
        if outcome["ok"]:
            with self.lock:
                self.garden.water(int(zone), outcome["seconds"])
                self.history.watered(int(zone), self.clock.hours())
            self.pump_until = time.monotonic() + outcome["seconds"]
        return outcome

    def _wait_for_pump(self):
        while time.monotonic() < self.pump_until + 0.5:
            time.sleep(0.2)

    def _show(self, icon):
        self.icon = icon
        self._mcu("show", icon)

    def _mcu(self, name, *args):
        try:
            return getattr(self.mcu, name)(*args)
        except Exception as error:
            print(f"MCU call {name} failed: {error}")
            return None

    # --- the log -----------------------------------------------------------------------

    def _write_log(self, kind, **fields):
        now = self.clock.now()
        day = (now - self.clock.start).days + 1
        entry = {"time": f"Day {day} {now:%H:%M}", "kind": kind, **fields}
        self.log.append(entry)
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as error:
            print(f"Could not write log: {error}")

    def _recent_log(self, n=8):
        lines = []
        for e in list(self.log)[-n:]:
            if e["kind"] == "decision":
                lines.append(f"{e['time']} zone {e['zone']}: {e['action']} {e['seconds'] or ''} - {e['reason']}")
            elif e["kind"] == "see":
                lines.append(f"{e['time']} photo: {e['status']} - {e['issue']}")
            elif e["kind"] == "ask":
                lines.append(f"{e['time']} gardener asked: {e['question']}")
        return "\n".join(lines)

    # --- the web page ------------------------------------------------------------------

    def state(self):
        now = self.clock.now()
        with self.lock:
            snap = self.garden.snapshot(now, self.real)
        icon = "water" if time.monotonic() < self.pump_until else self.icon
        return {
            "time": f"Day {(now - self.clock.start).days + 1} {now:%H:%M}",
            "garden": snap,
            "zones": {z: info for z, info in config.ZONES.items()},
            "icon": icon,
            "busy": self.busy,
            "busy_s": round(time.monotonic() - self.busy_since) if self.busy else None,
            "queued": self.jobs.qsize(),
            "gemma": "off" if self.llm is None else f"{self.llm.model} @ {self.llm.base_url or 'looking for the server…'}",
            "auto": self.auto_decide,
            "raw_sensors": self.raw,
            "camera": config.RECAMERA_URL or None,
            "test_photo": self.test_photo,
            "test_photos": list(config.TEST_PHOTOS),
            "bench": getattr(self.mcu, "bench", None),  # the laptop test bench's sliders, if any
            "wired": sorted(self.wired),
            "all_sensors": list(config.SENSOR_ORDER),
            "answer": self.answer,
            "photo": self.photo,
            "log": [{k: v for k, v in e.items() if k != "prompt"} for e in reversed(self.log)][:40],
            "last_prompt": next((e["prompt"] for e in reversed(self.log) if "prompt" in e), None),
        }

    def handle(self, action):
        """One endpoint for every button on the page."""
        kind = action.get("type")
        with self.lock:
            if kind == "scenario":
                self.garden.set_scenario(action["value"], self.clock.hours())
                self.last_decision_h = None  # let Gemma look at the new situation soon
            elif kind == "dry":
                self.garden.dry_out(int(action["zone"]))
            elif kind == "battery":
                self.garden.battery = float(action["value"])
            elif kind == "tank":
                self.garden.tank_empty = bool(action["empty"])
        if kind in ("scenario", "dry", "battery", "tank"):
            return {"ok": True}
        if kind == "wired":  # tick a sensor on the web page once it's plugged in (no code editing)
            if action.get("name") not in config.ALL_SENSORS:
                return {"ok": False, "error": f"unknown sensor {action.get('name')!r}"}
            (self.wired.add if action.get("on") else self.wired.discard)(action["name"])
            return {"ok": True}
        if kind == "auto":  # pause / resume Gemma's automatic decisions
            self.auto_decide = bool(action.get("on"))
            return {"ok": True}
        if kind == "test_photo":  # which drawing the pretend camera "sees"
            if action.get("value") not in config.TEST_PHOTOS:
                return {"ok": False, "error": f"unknown test photo {action.get('value')!r}"}
            self.test_photo = action["value"]
            return {"ok": True}
        if kind in ("bench", "button"):  # laptop test bench: sliders and the yellow button
            if getattr(self.mcu, "bench", None) is None:
                return {"ok": False, "error": "no test bench here - it only exists in laptop mode"}
            try:
                if kind == "bench":
                    self.mcu.set_bench(action["name"], action["value"])
                else:
                    self.mcu.press_button()
            except (ValueError, KeyError) as error:
                return {"ok": False, "error": str(error)}
            return {"ok": True}
        if kind == "decide":
            self.last_decision_h = self.clock.hours()
            self._enqueue("decide")
        elif kind == "ask":
            self.jobs.put(("ask", str(action["question"])[:300]))
        elif kind == "photo":
            self.jobs.put(("photo", {"image_b64": action["image_b64"], "mime": action.get("mime", "image/jpeg")}))
        elif kind == "journal":
            self._enqueue("journal")
        elif kind == "check":  # same as the yellow button
            self.check_now()
        elif kind == "water":  # the "try to overwater it" button: straight to the MCU, no Gemma
            outcome = self._act(int(action["zone"]), int(action["seconds"]))
            self._write_log("manual", zone=int(action["zone"]), seconds=int(action["seconds"]), mcu=outcome)
            return {"ok": True, "mcu": outcome}
        else:
            return {"ok": False, "error": f"unknown action {kind!r}"}
        return {"ok": True, "queued": self.jobs.qsize()}
