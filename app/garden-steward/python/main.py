"""Garden Steward - entry point when running on the Arduino UNO Q through App Lab.

For a laptop without the board, run laptop.py instead.
"""

import time

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App, Bridge

from brain import LlmClient
from mcu import BridgeMcu
from steward import Steward

steward = Steward(BridgeMcu(Bridge), LlmClient())
ui = WebUI()  # serves ../assets on port 7000


def api_state():
    return steward.state()


def api_action(payload: dict):  # VERIFY: FastAPI fills `payload` from the JSON body of the POST
    return steward.handle(payload)


ui.expose_api("GET", "/api/state", api_state)
ui.expose_api("POST", "/api/action", api_action)

steward.start()


def loop():
    steward.tick()
    time.sleep(1)


App.run(user_loop=loop)
