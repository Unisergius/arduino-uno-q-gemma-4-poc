import json
from datetime import datetime

import pytest

import brain
import config
from mcu import FakeMcu, SafetyRules
from simulation import PaperGarden, SimClock
from stats import History, describe, summarise
from steward import Steward


class ManualTime:
    """A real-time source we can move by hand."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_clock():
    fake = ManualTime()
    return SimClock(scale=60, start=datetime(2026, 6, 1, 6, 0), real_time=fake), fake


# --- clock and soil model ---------------------------------------------------------------


def test_clock_runs_sixty_times_faster():
    clock, fake = make_clock()
    fake.t = 60  # one real minute
    assert clock.hours() == pytest.approx(1.0)
    assert clock.now() == datetime(2026, 6, 1, 7, 0)


def test_soil_dries_faster_in_a_heatwave():
    noon = datetime(2026, 6, 1, 12, 0)
    normal, hot = PaperGarden(), PaperGarden()
    hot.set_scenario("heatwave", 0)
    normal.step(3, noon, 3)
    hot.step(3, noon, 3)
    assert hot.moisture[1] < normal.moisture[1] < 50


def test_watering_raises_moisture():
    garden = PaperGarden()
    garden.dry_out(1)
    garden.water(1, 30)
    assert garden.moisture[1] == pytest.approx(38.0)


def test_rain_coming_drops_pressure_then_rains():
    garden = PaperGarden()
    garden.set_scenario("rain_coming", 0)
    at = datetime(2026, 6, 1, 9, 0)
    for h in range(1, 5):
        garden.step(1, at, h)
    assert garden.pressure < 1010
    assert garden.raining


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        PaperGarden().set_scenario("snow", 0)


# --- stats ----------------------------------------------------------------------------


def history_with(points):
    history = History()
    for h, m1, pressure in points:
        history.add(h, {"moisture": {1: m1, 2: 50.0}, "temp_c": 27, "humidity": 40, "light": 80,
                        "pressure_hpa": pressure, "battery": 78, "tank_empty": False})
    return history


def test_summary_trend_and_pressure_change():
    history = history_with([(0, 40.0, 1010.0), (1, 37.0, 1009.0), (2, 34.0, 1008.0), (3, 31.0, 1006.0)])
    history.watered(1, 0)
    s = summarise(history, 3, datetime(2026, 6, 1, 9, 0))
    assert s["zones"][1]["trend_per_h"] == pytest.approx(-3.0)
    assert s["zones"][1]["hours_since_watered"] == 3
    assert s["zones"][2]["hours_since_watered"] is None
    assert s["pressure_change_3h"] == pytest.approx(-4.0)


def test_describe_mentions_everything_gemma_needs():
    history = history_with([(0, 40.0, 1010.0), (3, 31.0, 1006.0)])
    text = describe(summarise(history, 3, datetime(2026, 6, 1, 7, 10)))
    assert "Time 07:10." in text
    assert "Zone 1 tomatoes: soil 31.0 % (target 35-60 %), falling 3.0 %/h, never watered yet." in text
    assert "-4.0 hPa in 3 h (rain likely)" in text
    assert "Battery 78 %. Water tank ok." in text


# --- validation and fallback --------------------------------------------------------------


def test_validate_keeps_good_items_and_drops_bad_ones():
    answer = {"decisions": [
        {"zone": 1, "action": "water", "seconds": 30, "reason": "dry"},
        {"zone": 1, "action": "wait", "seconds": 0, "reason": "duplicate"},
        {"zone": 7, "action": "water", "seconds": 30, "reason": "no such zone"},
        {"zone": 2, "action": "dance", "seconds": 0, "reason": "no such action"},
    ]}
    assert brain.validate(answer) == [{"zone": 1, "action": "water", "seconds": 30, "reason": "dry"}]


def test_validate_rejects_garbage():
    for bad in [None, {}, {"decisions": "water"}, {"decisions": [{"zone": 1}]}]:
        with pytest.raises(ValueError):
            brain.validate(bad)


def test_validate_passes_long_waterings_through_for_the_mcu_to_clamp():
    answer = {"decisions": [{"zone": 1, "action": "water", "seconds": 600, "reason": "huge"}]}
    assert brain.validate(answer)[0]["seconds"] == 600


def test_fallback_waters_only_dry_zones():
    summary = {"zones": {1: {"moisture": 20.0}, 2: {"moisture": 50.0}}}
    decisions = brain.fallback(summary)
    assert decisions[0]["action"] == "water" and decisions[0]["seconds"] == config.FALLBACK_WATER_S
    assert decisions[1]["action"] == "wait"


# --- the safety rules (the MCU's job) -------------------------------------------------------


def test_safety_clamps_long_waterings():
    ok, seconds, note = SafetyRules().check(1, 600, now_h=0, battery=80, tank_empty=False)
    assert ok and seconds == config.MAX_PUMP_S and "clamped" in note


def test_safety_minimum_interval_and_daily_maximum():
    rules = SafetyRules()
    assert rules.check(1, 30, 0, 80, False)[0]
    ok, _, note = rules.check(1, 30, 2, 80, False)
    assert not ok and "minimum is 4 h" in note
    assert rules.check(1, 30, 4, 80, False)[0]
    assert rules.check(1, 30, 8, 80, False)[0]
    ok, _, note = rules.check(1, 30, 12, 80, False)
    assert not ok and "3 times" in note
    assert rules.check(2, 30, 12, 80, False)[0]  # other zone has its own budget
    assert rules.check(1, 30, 24.5, 80, False)[0]  # a day later the oldest one expired


def test_safety_battery_tank_and_bad_zone():
    rules = SafetyRules()
    assert "battery" in rules.check(1, 30, 0, 10, False)[2]
    assert "tank" in rules.check(1, 30, 0, 80, True)[2]
    assert "unknown zone" in rules.check(9, 30, 0, 80, False)[2]


def test_fake_mcu_uses_the_sim_clock():
    clock, fake = make_clock()
    mcu = FakeMcu(clock)
    mcu.set_sim_state(80, False)
    assert mcu.water(1, 30)["ok"]
    fake.t = 60 * 3  # 3 simulated hours later
    assert not mcu.water(1, 30)["ok"]
    fake.t = 60 * 4
    assert mcu.water(1, 30)["ok"]


# --- the decision loop with a stubbed Gemma ---------------------------------------------------


class StubLlm:
    """Answers like Gemma would, without a model."""

    model, base_url = "stub", "nowhere"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, system, user, schema=None, **kwargs):
        self.prompts.append((system, user, schema))
        if isinstance(self.reply, Exception):
            raise self.reply
        return json.dumps(self.reply), {"seconds": 1.0, "decode_tok_s": 9.9}


def steward_with(reply, tmp_path):
    clock, fake = make_clock()
    llm = StubLlm(reply)
    steward = Steward(FakeMcu(clock), llm, clock=clock, log_path=str(tmp_path / "log.jsonl"))
    return steward, llm, fake


def test_decision_waters_through_the_mcu_and_logs_the_reason(tmp_path):
    reply = {"decisions": [
        {"zone": 1, "reason": "Tomatoes are dry.", "action": "water", "seconds": 30},
        {"zone": 2, "reason": "Lettuce is fine.", "action": "wait", "seconds": 0},
    ]}
    steward, llm, _ = steward_with(reply, tmp_path)
    steward.garden.dry_out(1)
    steward.tick()
    kind, payload = steward.jobs.get_nowait()
    assert kind == "decide"
    steward._job_decide(payload)

    assert steward.garden.moisture[1] == pytest.approx(38.0)
    first = steward.log[0]
    assert first["source"] == "gemma" and first["mcu"]["ok"] and first["reason"] == "Tomatoes are dry."
    assert "Zone 1 tomatoes: soil 20.0 %" in llm.prompts[0][1]
    assert llm.prompts[0][2] == brain.decision_schema()
    assert (tmp_path / "log.jsonl").read_text().count("\n") == 2


def test_broken_gemma_falls_back_to_the_rule(tmp_path):
    steward, _, _ = steward_with(TimeoutError("too slow"), tmp_path)
    steward.garden.dry_out(2)
    steward.tick()
    steward._job_decide(None)
    by_zone = {e["zone"]: e for e in steward.log}
    assert by_zone[2]["action"] == "water" and by_zone[2]["source"] == "fallback"
    assert by_zone[1]["action"] == "wait"
    assert "too slow" in by_zone[1]["error"]


def test_partial_answer_is_completed_by_the_fallback(tmp_path):
    reply = {"decisions": [{"zone": 1, "reason": "ok", "action": "wait", "seconds": 0}]}
    steward, _, _ = steward_with(reply, tmp_path)
    steward.tick()
    steward._job_decide(None)
    assert [e["source"] for e in steward.log] == ["gemma+fallback", "gemma+fallback"]


def test_mcu_refusal_is_logged_and_shown(tmp_path):
    reply = {"decisions": [
        {"zone": 1, "reason": "Water a lot.", "action": "water", "seconds": 30},
        {"zone": 2, "reason": "fine", "action": "wait", "seconds": 0},
    ]}
    steward, _, _ = steward_with(reply, tmp_path)
    steward.handle({"type": "tank", "empty": True})
    steward.tick()
    steward._job_decide(None)
    assert steward.log[0]["mcu"] == {"ok": False, "zone": 1, "seconds": 0, "note": "water tank is empty"}
    assert steward.icon == "alert"


def test_ask_can_request_water_but_the_mcu_clamps_it(tmp_path):
    reply = {"answer": "Watering zone 1 now.", "water_zone": 1, "water_seconds": 600}
    steward, _, _ = steward_with(reply, tmp_path)
    steward.tick()
    steward.handle({"type": "ask", "question": "Water zone 1 for 10 minutes"})
    while not steward.jobs.empty():
        kind, payload = steward.jobs.get_nowait()
        getattr(steward, f"_job_{kind}")(payload)
    assert steward.answer["mcu"]["seconds"] == config.MAX_PUMP_S
    assert "clamped" in steward.answer["mcu"]["note"]


def test_forced_overwatering_is_refused_the_second_time(tmp_path):
    steward, _, _ = steward_with({}, tmp_path)
    steward.tick()
    first = steward.handle({"type": "water", "zone": 1, "seconds": 600})["mcu"]
    second = steward.handle({"type": "water", "zone": 1, "seconds": 600})["mcu"]
    assert first["ok"] and first["seconds"] == 60
    assert not second["ok"] and "minimum is 4 h" in second["note"]


def test_decisions_are_scheduled_every_two_sim_hours(tmp_path):
    steward, _, fake = steward_with({}, tmp_path)
    steward.tick()
    assert steward.jobs.get_nowait()[0] == "decide"
    fake.t = 60  # +1 h: not due yet
    steward.tick()
    assert steward.jobs.empty()
    fake.t = 120  # +2 h: due
    steward.tick()
    assert steward.jobs.get_nowait()[0] == "decide"


def test_state_is_json_ready(tmp_path):
    steward, _, _ = steward_with({}, tmp_path)
    steward.tick()
    state = json.loads(json.dumps(steward.state()))
    assert state["time"] == "Day 1 06:00"
    assert set(state["garden"]["moisture"]) == {"1", "2"}
    assert steward.handle({"type": "nope"})["ok"] is False
