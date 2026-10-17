"""Gemma 4's three jobs: Decide, See, Explain.

Gemma runs inside a local llama.cpp server. We ask it for JSON and pass a JSON
schema, which llama.cpp turns into a grammar: the model *cannot* produce broken
JSON. Python still checks the values, and the MCU still enforces the limits.
"""

import json
import time
import urllib.request

import config

ACTIONS = ("water", "wait", "alert")

DECIDE_PROMPT = """You are the Garden Steward, the brain of a small off-grid garden.
Every few hours you get a short report. For EACH zone choose one action:
- water: run the pump. 20-40 seconds is a normal drink; 60 seconds is the most it can do.
- wait: do nothing for now.
- alert: something needs a human; say what in the reason.
Rules, using the words in the report:
- VERY DRY or below target: water.
- in target range: wait, unless it is falling fast.
- above target: wait.
- If a zone says it is raining now or rain is likely: wait and say so - unless it is VERY DRY.
- If the water tank is EMPTY or the battery is under 20 %: alert instead of water.
Write the reason first: one plain sentence, at most 20 words."""

ASK_PROMPT = """You are the Garden Steward, the brain of a small off-grid garden.
Answer the gardener in 1-3 short, friendly sentences, using the report and the recent log.
Only if the gardener asks you to water, set water_zone and water_seconds; otherwise set both to 0.
Never mention water_zone or water_seconds in the answer."""

SEE_PROMPT = """This is a photo of the plants in the garden. They may be simple drawings on paper:
judge only colour and shape, never the amount of detail.
First describe the leaves: their colours and whether they stand up or hang down.
Then judge: green, upright leaves = healthy. Hanging or drooping leaves = thirsty.
Yellow, brown or spotted leaves = sick."""

JOURNAL_PROMPT = """You are the Garden Steward. Write today's garden journal entry in 2-3 short sentences
for the gardener: what the weather did, what you watered or skipped, and why."""


def decision_schema(zones=config.ZONES):
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "minItems": len(zones),
                "maxItems": len(zones),
                "items": {
                    "type": "object",
                    "properties": {
                        "zone": {"type": "integer", "enum": list(zones)},
                        "reason": {"type": "string", "maxLength": 160},
                        "action": {"type": "string", "enum": list(ACTIONS)},
                        "seconds": {"type": "integer", "minimum": 0, "maximum": 600},
                    },
                    "required": ["zone", "reason", "action", "seconds"],
                },
            }
        },
        "required": ["decisions"],
    }


def ask_schema(zones=config.ZONES):
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "maxLength": 400},
            "water_zone": {"type": "integer", "enum": [0, *zones]},
            "water_seconds": {"type": "integer", "minimum": 0, "maximum": 600},
        },
        "required": ["answer", "water_zone", "water_seconds"],
    }


SEE_SCHEMA = {
    "type": "object",
    "properties": {
        "leaves": {"type": "string", "maxLength": 120},  # describe first, then judge
        "status": {"type": "string", "enum": ["healthy", "thirsty", "sick", "unknown"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["leaves", "status", "confidence"],
}


def pick_model(configured, available):
    """The configured model if the server has it, else any Gemma 4 it serves.

    App Lab's llama.cpp runner names each model after its .gguf file, and the speed test may
    install a smaller Gemma 4 E2B file when the disk is tight - so the name can differ.
    """
    if not available or configured in available:
        return configured
    gemma4 = [m for m in available if "gemma-4" in m.lower()]
    return gemma4[0] if gemma4 else configured


class LlmClient:
    """A tiny client for llama.cpp's OpenAI-style /chat/completions endpoint."""

    def __init__(self, base_url=config.LLM_BASE_URL, model=config.LLM_MODEL, timeout=config.LLM_TIMEOUT_S):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._model_checked = False

    def _check_model(self):
        """Once, ask the server which models it has, and switch to its Gemma 4 if the name differs."""
        try:
            with urllib.request.urlopen(f"{self.base_url}/models", timeout=10) as response:
                available = [m["id"] for m in json.load(response).get("data", [])]
        except Exception:
            return  # server not up yet: try again next time
        self.model = pick_model(self.model, available)
        self._model_checked = True

    def chat(self, system, user, schema=None, max_tokens=200, image_b64=None, image_mime="image/jpeg", temperature=0.2):
        """Return (text, info). `info` has timing numbers for the log and the web page."""
        if not self._model_checked:
            self._check_model()
        content = user
        if image_b64:
            content = [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}},
            ]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
                # An empty assistant turn makes llama.cpp close Gemma's "thought" channel before it
                # starts. Together with a thinking budget of 0, Gemma answers straight away instead
                # of thinking out loud - which would cost minutes on the board. (Tested: 0 of 12
                # replies thought with both; 6 of 12 did without the budget.)
                {"role": "assistant", "content": ""},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_budget_tokens": 0,
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            reply = json.loads(response.read())
        seconds = time.monotonic() - started

        text = reply["choices"][0]["message"]["content"]
        timings = reply.get("timings", {})
        usage = reply.get("usage", {})
        info = {
            "seconds": round(seconds, 1),
            "prompt_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "prefill_tok_s": round(timings["prompt_per_second"], 1) if "prompt_per_second" in timings else None,
            "decode_tok_s": round(timings["predicted_per_second"], 1) if "predicted_per_second" in timings else None,
        }
        return text, info


# --- Job 1: Decide ------------------------------------------------------------------


def fallback(summary, zones=None):
    """The simple rule that keeps plants alive when Gemma is unavailable."""
    decisions = []
    for zone, z in summary["zones"].items():
        if zones is not None and zone not in zones:
            continue
        if z["moisture"] < config.URGENT_SOIL:
            decisions.append({"zone": zone, "action": "water", "seconds": config.FALLBACK_WATER_S,
                              "reason": f"Fallback rule: soil below {config.URGENT_SOIL} %."})
        else:
            decisions.append({"zone": zone, "action": "wait", "seconds": 0, "reason": "Fallback rule: soil is fine."})
    return decisions


def validate(answer, zones=config.ZONES):
    """Keep the well-formed decisions, at most one per zone. Raises ValueError if none are usable."""
    if not isinstance(answer, dict) or not isinstance(answer.get("decisions"), list):
        raise ValueError("answer has no 'decisions' list")
    good = {}
    for item in answer["decisions"]:
        try:
            zone, action, seconds = int(item["zone"]), item["action"], int(item["seconds"])
            reason = str(item.get("reason", "")).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if zone not in zones or action not in ACTIONS or zone in good:
            continue
        if action == "water" and seconds <= 0:
            continue
        good[zone] = {"zone": zone, "action": action, "seconds": seconds if action == "water" else 0, "reason": reason}
    if not good:
        raise ValueError("no usable decisions")
    return [good[z] for z in sorted(good)]


def decide(summary, summary_text, llm, zones=config.ZONES):
    """Ask Gemma what to do. Falls back to the simple rule for anything Gemma gets wrong."""
    try:
        text, info = llm.chat(DECIDE_PROMPT, summary_text, schema=decision_schema(zones), max_tokens=220, temperature=0)
        decisions = validate(json.loads(text), zones)
    except Exception as error:  # timeout, server down, bad JSON...
        return {"decisions": fallback(summary), "source": "fallback", "llm": None, "error": str(error)}

    missing = [z for z in zones if z not in {d["zone"] for d in decisions}]
    source = "gemma"
    if missing:
        decisions += fallback(summary, missing)
        source = "gemma+fallback"
    return {"decisions": decisions, "source": source, "llm": info, "error": None}


# --- Job 2: See ---------------------------------------------------------------------


def check_photo(image_b64, llm, image_mime="image/jpeg"):
    text, info = llm.chat(SEE_PROMPT, "How do these plants look?", schema=SEE_SCHEMA,
                          max_tokens=80, image_b64=image_b64, image_mime=image_mime, temperature=0)
    verdict = json.loads(text)
    verdict["leaves"] = tidy_cut(verdict["leaves"], SEE_SCHEMA["properties"]["leaves"]["maxLength"])
    return verdict, info


def tidy_cut(text, limit):
    """The schema stops Gemma mid-sentence at `limit` characters: keep whole sentences, or whole words + "…"."""
    text = text.strip()
    if len(text) < limit - 1:
        return text
    end = text.rfind(". ")
    if end > limit // 3:
        return text[: end + 1]
    return text.rsplit(" ", 1)[0].rstrip(",;:") + "…"


# --- Job 3: Explain -----------------------------------------------------------------


def ask(question, summary_text, recent_log, llm, zones=config.ZONES):
    user = f"Report:\n{summary_text}\n\nRecent log:\n{recent_log or '(empty)'}\n\nGardener: {question}"
    text, info = llm.chat(ASK_PROMPT, user, schema=ask_schema(zones), max_tokens=160)
    return json.loads(text), info


def journal(summary_text, day_log, llm):
    user = f"Report now:\n{summary_text}\n\nToday's log:\n{day_log or '(nothing happened)'}"
    return llm.chat(JOURNAL_PROMPT, user, max_tokens=140)
