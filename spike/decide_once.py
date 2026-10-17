"""Ask Gemma for two real garden decisions (and optionally look at a photo); print a results table.

The first decision reads the whole prompt ("cold"). The second has a different report but the same
instructions, so llama-server can reuse the unchanged start of the prompt ("warm"): that is the
speed the garden gets every time after the first.

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


def example_summary(later=False):
    """Dry tomatoes on a warm morning (as in docs/design.md); `later`: the same garden 4 hours on."""
    history = History()
    readings = [(0, 40, 1010.0), (1, 37, 1009.0), (2, 34, 1008.0), (3, 28, 1006.0)]
    if later:
        readings = [(4, 52, 1006.0), (5, 49, 1007.0), (6, 46, 1008.0), (7, 44, 1009.0)]
    for h, tomatoes, pressure in readings:
        history.add(h, {"moisture": {1: tomatoes, 2: 47 if later else 52}, "temp_c": 30 if later else 27,
                        "humidity": 35 if later else 40, "light": 90 if later else 70,
                        "pressure_hpa": pressure, "battery": 78, "tank_empty": False, "raining": False})
    history.watered(1, 3.5 if later else -19)
    return summarise(history, 7 if later else 3, datetime(2026, 6, 1, 11 if later else 7, 10))


def print_decision(title, text, result):
    info = result["llm"] or {}
    print(f"### {title}")
    print()
    print("| What | Value |")
    print("|---|---|")
    print(f"| Source | {result['source']} {('(error: ' + result['error'] + ')') if result['error'] else ''} |")
    print(f"| Total time | {info.get('seconds')} s (goal: under 90 s) |")
    print(f"| Prompt / answer tokens | {info.get('prompt_tokens')} / {info.get('output_tokens')} |")
    print(f"| Prompt tokens actually read (rest reused) | {info.get('prompt_read', 'n/a')} |")
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
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="gemma-4-E2B_q4_0-it")
    parser.add_argument("--photo", help="a JPEG or PNG of your (paper) garden")
    args = parser.parse_args()

    llm = brain.LlmClient(base_url=args.url, model=args.model, timeout=900)
    for title, later in (("Decision 1 (cold: reads the whole prompt)", False),
                         ("Decision 2 (warm: same instructions, new report)", True)):
        summary = example_summary(later)
        text = describe(summary)
        print_decision(title, text, brain.decide(summary, text, llm))

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
