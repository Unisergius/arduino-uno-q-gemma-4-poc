"""Run the Garden Steward on a laptop: a pretend MCU instead of the board, same web page.

    python laptop.py                      # Gemma via llama-server on http://localhost:8080/v1
    python laptop.py --no-llm             # no Gemma: only the fallback rule
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--llm-url", default=os.getenv("LLM_BASE_URL", "http://localhost:8080/v1"))
    parser.add_argument("--model", default=config.LLM_MODEL)
    parser.add_argument("--no-llm", action="store_true", help="run without Gemma (fallback rule only)")
    args = parser.parse_args()

    clock = SimClock()
    llm = None if args.no_llm else LlmClient(base_url=args.llm_url, model=args.model)
    steward = Steward(FakeMcu(clock), llm, clock=clock)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(steward))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    steward.start()
    print(f"Garden Steward running. Open http://localhost:{args.port} (Ctrl+C to stop)")
    try:
        while True:
            steward.tick()
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
