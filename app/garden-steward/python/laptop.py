"""The test environment: run the Garden Steward on a laptop, with no board and no camera.

A pretend MCU (same safety rules) replaces the board, and the web page gets a "test bench":
sliders for the knob, soil probe, temperature, light and rain sensor, and the yellow button.
With no camera, "Check now" shows Gemma one of the built-in test drawings.

    python laptop.py                      # Gemma via llama-server on http://localhost:8080/v1
    python laptop.py --no-llm             # no Gemma: only the fallback rule
    python laptop.py --no-bench           # no pretend sensors: the soil dries out by itself
    python laptop.py --llm-url http://192.168.1.50:9999/v1   # Gemma running on the UNO Q
"""

import argparse
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import config
from brain import LlmClient
from mcu import FakeMcu
from simulation import SimClock
from steward import Steward

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")


def make_handler(steward):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=ASSETS, **kwargs)

        def do_GET(self):
            if self.path == "/api/state":
                self._json(steward.state())
            else:
                super().do_GET()

        def do_POST(self):
            if self.path != "/api/action":
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self._json(steward.handle(json.loads(body or b"{}")))

        def _json(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # keep the terminal quiet

    return Handler


def bind(handler, port, tries=20):
    """Port 7000 like on the board. On a Mac, AirPlay Receiver usually has it, so try the next ones."""
    for candidate in range(port, port + tries):
        try:
            server = ThreadingHTTPServer(("0.0.0.0", candidate), handler)
        except OSError:
            continue
        if candidate != port:
            print(f"Port {port} is busy (on a Mac: usually AirPlay Receiver), using {candidate} instead.")
        return server
    raise SystemExit(f"No free port between {port} and {port + tries - 1}. Pick one with --port, e.g. --port 8123")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--llm-url", default=os.getenv("LLM_BASE_URL", "http://localhost:8080/v1"))
    parser.add_argument("--model", default=config.LLM_MODEL)
    parser.add_argument("--no-llm", action="store_true", help="run without Gemma (fallback rule only)")
    parser.add_argument("--no-bench", action="store_true", help="no pretend sensors: everything is simulated")
    args = parser.parse_args()

    clock = SimClock()
    llm = None if args.no_llm else LlmClient(base_url=args.llm_url, model=args.model)
    bench = not args.no_bench
    steward = Steward(FakeMcu(clock, bench=bench), llm, clock=clock,
                      wired=config.ALL_SENSORS if bench else set())

    server = bind(make_handler(steward), args.port)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    steward.start()
    print(f"Garden Steward running. Open http://localhost:{port} (Ctrl+C to stop)")
    try:
        while True:
            steward.tick()
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
