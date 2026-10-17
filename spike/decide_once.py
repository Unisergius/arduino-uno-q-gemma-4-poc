"""Ask Gemma for one real garden decision (and optionally look at a photo); print a results table.

Uses the app's own prompt and JSON schema, so this is exactly what the Garden Steward will do.
    python3 decide_once.py --url http://127.0.0.1:8080/v1 [--photo garden.jpg]
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "garden-steward", "python"))

import brain  # noqa: E402
from stats import History, describe, summarise  # noqa: E402


def example_summary():
    """Dry tomatoes on a warm morning - the same situation as in docs/design.md."""
    history = History()
    for h, tomatoes, pressure in [(0, 40, 1010.0), (1, 37, 1009.0), (2, 34, 1008.0), (3, 28, 1006.0)]:
        history.add(h, {"moisture": {1: tomatoes, 2: 52}, "temp_c": 27, "humidity": 40, "light": 70,
                        "pressure_hpa": pressure, "battery": 78, "tank_empty": False, "raining": False})
    history.watered(1, -19)
    return summarise(history, 3, datetime(2026, 6, 1, 7, 10))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma-4-E2B_q4_0-it")
    parser.add_argument("--photo", help="a JPEG or PNG of your (paper) garden")
    args = parser.parse_args()

    llm = brain.LlmClient(base_url=args.url, model=args.model, timeout=900)
    summary = example_summary()
    text = describe(summary)
    result = brain.decide(summary, text, llm)
    info = result["llm"] or {}

    print("### One decision")
    print()
    print("| What | Value |")
    print("|---|---|")
    print(f"| Source | {result['source']} {('(error: ' + result['error'] + ')') if result['error'] else ''} |")
    print(f"| Total time | {info.get('seconds')} s (goal: under 90 s) |")
    print(f"| Prompt / answer tokens | {info.get('prompt_tokens')} / {info.get('output_tokens')} |")
    print(f"| Reading speed (prefill) | {info.get('prefill_tok_s')} tok/s |")
    print(f"| Writing speed (decode) | {info.get('decode_tok_s')} tok/s |")
    print()
    print("Prompt:")
    print("```")
    print(text)
    print("```")
    print("Gemma's decision:")
    print("```json")
    print(json.dumps(result["decisions"], indent=1))
    print("```")

    if args.photo:
        with open(args.photo, "rb") as f:
            image = base64.b64encode(f.read()).decode()
        try:
            mime = "image/png" if args.photo.lower().endswith(".png") else "image/jpeg"
            verdict, see = brain.check_photo(image, llm, mime)
            print()
            print(f"### Photo check ({os.path.basename(args.photo)}): {verdict} - {see['seconds']} s")
        except Exception as error:  # vision part missing, image too big, ...
            print()
            print(f"### Photo check failed: {error}")


if __name__ == "__main__":
    main()
