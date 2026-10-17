import json
from datetime import datetime

import pytest

import brain
import config
import sensors
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


def test_simulated_soil_dries_faster_in_a_heatwave():
    noon = datetime(2026, 6, 1, 12, 0)
    normal, hot = PaperGarden(), PaperGarden()
    hot.set_scenario("heatwave", 0)
    normal.step(3, noon, 3)
    hot.step(3, noon, 3)
    assert hot.soil(1, {}) < normal.soil(1, {}) < 50


def test_watering_bonus_is_added_and_fades_over_six_hours():
    garden = PaperGarden()
    garden.dry_out(1)
    garden.water(1, 30)
    knob = {"soil": {1: 20.0, 2: None}}
    assert garden.soil(1, knob) == pytest.approx(20 + config.WATERING_BONUS)
    night = datetime(2026, 6, 1, 23, 0)
    garden.step(3, night, 3, knob)
    assert garden.soil(1, knob) == pytest.approx(20 + config.WATERING_BONUS / 2)
    garden.step(3, night, 6, knob)
    assert garden.soil(1, knob) == pytest.approx(20.0)


def test_real_readings_win_over_the_simulation():
    garden = PaperGarden()
    real = {"soil": {1: 12.0, 2: None}, "temp_c": 31.5, "light": 5.0, "raining": True}
    snap = garden.snapshot(datetime(2026, 6, 1, 12, 0), real)
    assert snap["moisture"] == {1: 12.0, 2: 50.0}
    assert snap["temp_c"] == 31.5 and snap["light"] == 5.0 and snap["raining"]
    assert snap["sources"]["soil"] == {1: "sensor", 2: "simulated"}
    assert snap["sources"]["temp"] == "sensor"


def test_rain_on_the_steam_sensor_waters_the_paper_garden():
    garden = PaperGarden()
    garden.step(2, datetime(2026, 6, 1, 12, 0), 2, {"soil": {1: 30.0, 2: 30.0}, "raining": True})
    assert garden.soil(1, {"soil": {1: 30.0}}) == pytest.approx(30 + 2 * config.RAIN_BONUS_PER_H)


def test_rain_coming_drops_pressure_then_rains():
    garden = PaperGarden()
    garden.set_scenario("rain_coming", 0)
    at = datetime(2026, 6, 1, 9, 0)
    for h in range(1, 5):
        garden.step(1, at, h)
    assert garden.pressure < 1010
    assert garden.raining({})


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        PaperGarden().set_scenario("snow", 0)


# --- sensors ----------------------------------------------------------------------------


def test_raw_readings_become_percent_celsius_and_rain():
    raw = {"a0": 512, "a1": 350, "a2": 78, "a3": 400, "a4": 600, "button": 2}
    real = sensors.convert(raw, connected=config.ALL_SENSORS)
    assert real["soil"] == {1: pytest.approx(50.0, abs=0.1), 2: 50.0}
    assert real["temp_c"] == pytest.approx(25.2, abs=0.1)  # 78 / 1023 * 3.3 V * 100
    assert real["light"] == 50.0
    assert real["raining"] is True
    assert real["button"] == 2


def test_implausible_temperature_and_unconnected_sensors_are_ignored():
    raw = {"a0": 512, "a1": 350, "a2": 1000, "a3": 400, "a4": 0}
    real = sensors.convert(raw, connected={"knob", "temp"})
    assert real["temp_c"] is None  # 322 °C: unplugged or noise
    assert real["soil"][2] is None and real["light"] is None and real["raining"] is None
    assert sensors.convert({}) == {}


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


def test_describe_does_the_comparisons_for_gemma():
    history = history_with([(0, 20.0, 1015.0), (3, 20.0, 1015.0)])
    history.add(3, {"moisture": {1: 20.0, 2: 80.0}, "temp_c": 20, "humidity": 50, "light": 50,
                    "pressure_hpa": 1015.0, "battery": 78, "tank_empty": False, "raining": True})
    text = describe(summarise(history, 3, datetime(2026, 6, 1, 7, 10)))
    assert "soil 20.0 % = VERY DRY" in text and "soil 80.0 % = above target" in text
    assert text.count("it is raining now") == 2


def test_describe_mentions_everything_gemma_needs():
    history = history_with([(0, 40.0, 1010.0), (3, 31.0, 1006.0)])
    text = describe(summarise(history, 3, datetime(2026, 6, 1, 7, 10)))
    assert "Time 07:10." in text
    assert ("Zone 1 tomatoes: soil 31.0 % = below target (target 35-60 %), falling fast 3.0 %/h, "
            "never watered yet; rain likely in the next hours.") in text
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

    assert steward.garden.soil(1, {}) == pytest.approx(20 + config.WATERING_BONUS)
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


def test_decisions_are_scheduled_every_few_sim_hours(tmp_path):
    steward, _, fake = steward_with({}, tmp_path)
    steward.tick()
    assert steward.jobs.get_nowait()[0] == "decide"
    fake.t = 60 * (config.DECIDE_EVERY_H - 1)  # 1 h early: not due yet
    steward.tick()
    assert steward.jobs.empty()
    fake.t = 60 * config.DECIDE_EVERY_H  # due
    steward.tick()
    assert steward.jobs.get_nowait()[0] == "decide"


class SensorMcu(FakeMcu):
    """FakeMcu with a knob, a probe and a button."""

    def __init__(self, clock):
        super().__init__(clock)
        self.raw = {"a0": 1023, "a1": 700, "a2": 70, "a3": 800, "a4": 0, "button": 0}

    def read_sensors(self):
        return dict(self.raw)


def test_decision_sees_a_button_press_made_just_before(tmp_path):
    reply = {"decisions": [{"zone": 1, "reason": "dry", "action": "water", "seconds": 30},
                           {"zone": 2, "reason": "ok", "action": "wait", "seconds": 0}]}
    steward, llm, _ = steward_with(reply, tmp_path)
    steward.tick()
    steward.handle({"type": "dry", "zone": 1})  # no tick in between
    steward._job_decide(None)
    assert "Zone 1 tomatoes: soil 20.0 % = VERY DRY" in llm.prompts[0][1]


def test_yellow_button_takes_a_photo_and_decides(tmp_path):
    clock, _ = make_clock()
    mcu = SensorMcu(clock)
    steward = Steward(mcu, StubLlm({}), clock=clock, log_path=str(tmp_path / "log.jsonl"), wired=config.ALL_SENSORS)
    steward.tick()
    while not steward.jobs.empty():
        steward.jobs.get_nowait()  # drop the first scheduled decision
    mcu.raw["button"] = 1
    steward.tick()
    assert [steward.jobs.get_nowait()[0] for _ in range(2)] == ["snap", "decide"]


def test_pressing_again_while_gemma_looks_queues_nothing_more(tmp_path):
    clock, _ = make_clock()
    mcu = SensorMcu(clock)
    steward = Steward(mcu, StubLlm({}), clock=clock, log_path=str(tmp_path / "log.jsonl"), wired=config.ALL_SENSORS)
    steward.tick()
    while not steward.jobs.empty():
        steward.jobs.get_nowait()
    for presses in range(1, 6):
        mcu.raw["button"] = presses
        steward.tick()
    assert steward._waiting() == ["snap", "decide"]
    steward.jobs.get_nowait()
    steward.busy = "snap"  # still looking at the photo
    mcu.raw["button"] = 6
    steward.tick()
    assert steward._waiting() == ["decide"]
    assert steward.state()["busy_s"] is not None


def test_second_zone_waits_for_the_pump(tmp_path, monkeypatch):
    reply = {"decisions": [{"zone": 1, "reason": "dry", "action": "water", "seconds": 30},
                           {"zone": 2, "reason": "dry too", "action": "water", "seconds": 30}]}
    steward, _, _ = steward_with(reply, tmp_path)
    calls = []
    monkeypatch.setattr(steward, "_wait_for_pump", lambda: calls.append(steward.pump_until))
    steward.tick()
    steward._job_decide(None)
    assert len(calls) == 2 and calls[1] > calls[0]  # the second watering waited for the first one's pump time
    assert [e["mcu"]["ok"] for e in steward.log] == [True, True]


def test_knob_turned_to_dry_reaches_gemma(tmp_path):
    clock, _ = make_clock()
    mcu = SensorMcu(clock)
    reply = {"decisions": [{"zone": 1, "reason": "dry", "action": "water", "seconds": 30},
                           {"zone": 2, "reason": "ok", "action": "wait", "seconds": 0}]}
    llm = StubLlm(reply)
    steward = Steward(mcu, llm, clock=clock, log_path=str(tmp_path / "log.jsonl"), wired=config.ALL_SENSORS)
    mcu.raw["a0"] = 100  # knob almost fully "dry"
    steward.tick()
    steward._job_decide(None)
    assert "Zone 1 tomatoes: soil 9.8 %" in llm.prompts[0][1]
    assert steward.garden.soil(1, steward.real) == pytest.approx(9.8 + config.WATERING_BONUS)


def test_snap_without_camera_shows_gemma_the_picked_test_drawing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RECAMERA_URL", "")
    steward, llm, _ = steward_with({"leaves": "yellow and brown", "status": "sick", "confidence": "high"}, tmp_path)
    assert steward.handle({"type": "test_photo", "value": "sick"})["ok"]
    steward._job_snap(None)
    assert llm.prompts, "Gemma was asked to look"
    assert steward.photo["status"] == "sick"
    assert steward.log[-1]["test_photo"] == "sick"


def test_cut_off_photo_descriptions_end_cleanly():
    # Real Gemma 4 E2B output, stopped by the 120-character limit in the middle of a sentence.
    healthy = "The tomato plant (Zone 1) has green leaves that stand upright. The lettuce plant (Zone 2) has green, ruffled leaves that"
    sick = "Zone 1 (tomatoes) has elongated, somewhat oval leaves that are predominantly brown/yellow with some darker markings. The"
    assert brain.tidy_cut(healthy, 120) == "The tomato plant (Zone 1) has green leaves that stand upright."
    assert brain.tidy_cut(sick, 120).endswith("with some darker markings.")
    assert brain.tidy_cut("Green and upright.", 120) == "Green and upright."
    assert brain.tidy_cut("x" * 10 + " yellow leaves with brown spots all over the" + " y" * 40, 120).endswith("…")


def test_pick_model_finds_the_installed_gemma_4():
    assert brain.pick_model("gemma-4-E2B_q4_0-it", ["gemma-4-E2B_q4_0-it", "gemma-3-1b-it-Q4_0"]) == "gemma-4-E2B_q4_0-it"
    assert brain.pick_model("gemma-4-E2B_q4_0-it", ["Qwen3.5-0.8B-Q4_0", "gemma-4-E2B-it-Q3_K_M"]) == "gemma-4-E2B-it-Q3_K_M"
    assert brain.pick_model("gemma-4-E2B_q4_0-it", ["gemma-3-1b-it-Q4_0"]) == "gemma-4-E2B_q4_0-it"  # no Gemma 4: keep asking for it
    assert brain.pick_model("gemma-4-E2B_q4_0-it", []) == "gemma-4-E2B_q4_0-it"


def test_pick_server_prefers_the_one_with_gemma_4():
    answers = [("http://localhost:8080/v1", ["Qwen3.5-0.8B-Q4_0"]),
               ("http://172.17.0.1:8080/v1", ["gemma-4-E2B_q4_0-it"])]
    assert brain.pick_server(answers) == ("http://172.17.0.1:8080/v1", ["gemma-4-E2B_q4_0-it"])
    assert brain.pick_server(answers[:1])[0] == "http://localhost:8080/v1"
    assert brain.pick_server([]) == (None, [])


def test_candidate_urls_start_with_our_own_server():
    urls = brain.candidate_urls()
    assert urls[0] == "http://localhost:8080/v1"
    assert urls[-1] == "http://llamacpp-models-runner:9999/v1"


def test_auto_without_any_server_says_how_to_start_one(monkeypatch):
    monkeypatch.setattr(brain, "candidate_urls", lambda: ["http://127.0.0.1:9/v1"])  # nothing listens there
    llm = brain.LlmClient(base_url="auto")
    with pytest.raises(RuntimeError, match="serve_gemma.sh"):
        llm.chat("system", "user")


def test_pausing_automatic_decisions(tmp_path):
    steward, _, fake = steward_with({}, tmp_path)
    assert steward.handle({"type": "auto", "on": False})["ok"]
    steward.tick()
    assert steward.jobs.empty(), "no automatic decision while paused"
    assert steward.state()["auto"] is False
    steward.handle({"type": "decide"})  # asking by hand still works
    assert steward.jobs.get_nowait()[0] == "decide"
    steward.handle({"type": "auto", "on": True})
    fake.t = 60 * config.DECIDE_EVERY_H  # the next automatic decision comes on schedule again
    steward.tick()
    assert steward.jobs.get_nowait()[0] == "decide"


def test_unknown_test_drawing_is_refused(tmp_path):
    steward, _, _ = steward_with({}, tmp_path)
    assert steward.handle({"type": "test_photo", "value": "cactus"})["ok"] is False
    assert steward.test_photo == "healthy"


def test_every_test_drawing_exists():
    import camera

    for name in config.TEST_PHOTOS:
        assert len(camera.test_photo_b64(name)) > 1000


# --- the laptop test bench ------------------------------------------------------------------


def test_bench_sliders_go_through_the_real_sensor_code():
    clock, _ = make_clock()
    mcu = FakeMcu(clock, bench=True)
    for name, value in {"knob": 20, "soil": 80, "temp_c": 31, "light": 50, "raining": True}.items():
        mcu.set_bench(name, value)
    real = sensors.convert(mcu.read_sensors(), connected=config.ALL_SENSORS)
    assert real["soil"] == {1: pytest.approx(20, abs=0.5), 2: pytest.approx(80, abs=0.5)}
    assert real["temp_c"] == pytest.approx(31, abs=0.5)
    assert real["light"] == pytest.approx(50, abs=0.5)
    assert real["raining"] is True


def test_bench_yellow_button_takes_a_photo_and_decides(tmp_path):
    clock, _ = make_clock()
    steward = Steward(FakeMcu(clock, bench=True), StubLlm({}), clock=clock, log_path=str(tmp_path / "log.jsonl"),
                      wired=config.ALL_SENSORS)
    steward.tick()
    while not steward.jobs.empty():
        steward.jobs.get_nowait()  # drop the first scheduled decision
    assert steward.handle({"type": "button"})["ok"]
    steward.tick()
    assert [steward.jobs.get_nowait()[0] for _ in range(2)] == ["snap", "decide"]


def test_bench_actions_need_a_bench(tmp_path):
    steward, _, _ = steward_with({}, tmp_path)  # FakeMcu without a bench, like the board
    assert steward.handle({"type": "bench", "name": "knob", "value": 10})["ok"] is False
    assert steward.handle({"type": "button"})["ok"] is False
    clock, _ = make_clock()
    bench = Steward(FakeMcu(clock, bench=True), None, clock=clock, log_path=str(tmp_path / "b.jsonl"))
    assert bench.handle({"type": "bench", "name": "humidity", "value": 10})["ok"] is False
    assert bench.state()["bench"]["knob"] == 60


def test_state_is_json_ready(tmp_path):
    steward, _, _ = steward_with({}, tmp_path)
    steward.tick()
    state = json.loads(json.dumps(steward.state()))
    assert state["time"] == "Day 1 06:00"
    assert set(state["garden"]["moisture"]) == {"1", "2"}
    assert steward.handle({"type": "nope"})["ok"] is False


def test_applab_zip_matches_the_app():
    import importlib.util
    import os
    import zipfile

    root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
    zip_path = os.path.join(root, "dist", "garden-steward-applab.zip")
    if not os.path.exists(zip_path):
        pytest.skip("no App Lab zip built")
    spec = importlib.util.spec_from_file_location("make_applab_zip", os.path.join(root, "tools", "make_applab_zip.py"))
    maker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maker)
    expected = {}
    for path, arcname in maker.app_files():
        with open(path, "rb") as f:
            expected[arcname] = f.read()
    with zipfile.ZipFile(zip_path) as archive:
        actual = {name: archive.read(name) for name in archive.namelist()}
    assert actual == expected, "dist/garden-steward-applab.zip is out of date: run python3 tools/make_applab_zip.py"


def test_nothing_wired_by_default_so_floating_pins_are_ignored(tmp_path):
    clock, _ = make_clock()
    mcu = SensorMcu(clock)
    mcu.raw.update({"a0": 3, "a4": 1000})  # noise on unwired pins: "bone dry" and "raining"
    steward = Steward(mcu, None, clock=clock, log_path=str(tmp_path / "log.jsonl"))
    steward.tick()
    snap = steward.garden.snapshot(clock.now(), steward.real)
    assert snap["sources"]["soil"] == {1: "simulated", 2: "simulated"}
    assert snap["raining"] is False


def test_ticking_a_wired_sensor_on_the_web_page(tmp_path):
    clock, _ = make_clock()
    mcu = SensorMcu(clock)
    mcu.raw["a1"] = 0  # soil probe in the air: bone dry
    steward = Steward(mcu, None, clock=clock, log_path=str(tmp_path / "log.jsonl"))
    assert steward.state()["wired"] == []
    assert steward.handle({"type": "wired", "name": "soil", "on": True})["ok"]
    steward.tick()
    assert steward.garden.snapshot(clock.now(), steward.real)["sources"]["soil"][2] == "sensor"
    assert steward.handle({"type": "wired", "name": "soil", "on": False})["ok"]
    assert steward.handle({"type": "wired", "name": "radar", "on": True})["ok"] is False
    assert steward.state()["wired"] == []
