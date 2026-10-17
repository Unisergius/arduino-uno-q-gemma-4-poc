// Garden Steward - microcontroller side (STM32U585).
//
// The MCU owns everything physical: sensors, the "pump" relay, the LEDs and the
// LED matrix. It also enforces the SAFETY LIMITS. Gemma (on the Linux side) can
// only *ask* to water; this sketch decides whether that is allowed.
// Keep the limits in sync with python/config.py, and the pins with README.md.
//
// Paper Garden: no real water. The relay clicks, the blue LED and the matrix
// show "watering", and Python adds a pretend watering bonus to the soil reading.

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>

// ---- Wiring: DFRobot Gravity kit (3.3 V logic! A0/A1 are not 5 V tolerant, D3 unused) ----
const int PIN_KNOB = A0;     // Analog Rotation Sensor: zone 1 "soil dial"      (VCC 3.3 V)
const int PIN_SOIL = A1;     // Soil Moisture Sensor SEN0114: zone 2 probe      (VCC 3.3 V)
const int PIN_TEMP = A2;     // LM35 DFR0023: 10 mV/°C, only ~0.25 V out         (VCC 5 V ok)
const int PIN_LIGHT = A3;    // Ambient Light Sensor                             (VCC 3.3 V)
const int PIN_STEAM = A4;    // Steam Sensor: wet fingertip = "raining now"      (VCC 3.3 V)
const int PIN_BUTTON = 2;    // yellow push button: "check now"                 (VCC 3.3 V)
const int PIN_RELAY = 4;     // Relay Module DFR0017: the "pump"                 (VCC 5 V)
const int PIN_LED_WATER = 5; // blue LED module (optional)
const int PIN_LED_ALERT = 6; // red LED module (optional)
const int BUTTON_PRESSED = HIGH;  // VERIFY: the Gravity button reads HIGH while pressed
// VERIFY: the DFR0017 relay is powered from 5 V; check its input switches with the UNO Q's 3.3 V signal.

// ---- Safety limits (same values as python/config.py) ----
const int MAX_PUMP_S = 60;                 // longest single watering, seconds
const long MIN_INTERVAL_MIN = 4L * 60;     // per zone, simulated minutes
const int MAX_PER_DAY = 3;                 // per zone, per 24 simulated hours
const int BATTERY_FLOOR = 20;              // %, no watering below this

// Simulated time: 1 real second = 1 simulated minute (TIME_SCALE = 60).
// The intervals above are measured on this scaled clock. Use 1 for a real garden.
const long TIME_SCALE = 60;

const int ZONES = 2;  // one pump/relay; in a real garden each zone would get a valve

Arduino_LED_Matrix matrix;
// What the matrix shows (see "LED matrix" below). Declared up here because the Arduino
// builder puts its function prototypes before the first function.
enum Mode { IDLE, THINK, OK, ALERT };
enum Flash { NO_FLASH, ACK, NOPE };

// Simulated battery and tank, sent by Python. On a real garden these would be read
// from a battery monitor and a float switch instead.
int battery = 100;
bool tankEmpty = false;

// Watering history per zone (simulated minutes), oldest first.
long history[ZONES + 1][MAX_PER_DAY];
int historyCount[ZONES + 1] = {0};

int pumpZone = 0;                // 0 = pump off
unsigned long pumpOffAt = 0;

// Button presses are counted here; Python notices when the count goes up.
long buttonPresses = 0;
bool buttonWasDown = false;
unsigned long buttonChangedAt = 0;

long simMinutes() {
  return (long)(millis() / 1000UL) * TIME_SCALE / 60;
}

// ---------------------------------------------------------------- LED matrix
// What the 8 x 13 matrix shows, most important first:
//   drops falling           the pump is on
//   a ripple / a blinking X  the yellow button was taken / ignored because Gemma is busy
//   a spinning circle        Gemma is thinking (Python says "think")
//   a check mark / a "!"     the result ("ok" / "alert"), for RESULT_MS
//   a pause sign             idle
// Every frame is drawn here, so the Bridge only carries the changes of state.

const unsigned long RESULT_MS = 6000;       // then back to the pause sign
const unsigned long FLASH_MS = 600;
const unsigned long BUTTON_WAIT_MS = 5000;  // the button starts the circle; Python confirms within ~1 s

Mode mode = IDLE;
Flash flash = NO_FLASH;
unsigned long modeSince = 0, flashSince = 0, lastFrame = 0;
bool thinkFromButton = false;  // the circle was started by the button, not yet by Python
int step = 0;                  // animation frame counter

// The loading circle, clockwise from the top.
const int RING[][2] = {{0, 6}, {0, 7}, {1, 8}, {2, 9}, {3, 9}, {4, 9}, {5, 9}, {6, 8}, {7, 7},
                       {7, 6}, {7, 5}, {6, 4}, {5, 3}, {4, 3}, {3, 3}, {2, 3}, {1, 4}, {0, 5}};
const int RING_N = sizeof(RING) / sizeof(RING[0]);
// The check mark, in drawing order.
const int CHECK[][2] = {{4, 2}, {5, 3}, {6, 4}, {7, 5}, {6, 6}, {5, 7}, {4, 8}, {3, 9}, {2, 10}, {1, 11}};
const int CHECK_N = sizeof(CHECK) / sizeof(CHECK[0]);

uint8_t frame[8 * 13];

void px(int row, int col, uint8_t level = 7) {  // level 0-7 (3-bit grayscale)
  if (row >= 0 && row < 8 && col >= 0 && col < 13) frame[row * 13 + col] = level;
}

void drawFrame(unsigned long now) {
  memset(frame, 0, sizeof(frame));
  if (pumpZone) {                                // three drops falling onto the soil
    const int cols[] = {2, 6, 10}, offsets[] = {0, 5, 2};
    for (int j = 0; j < 3; j++) {
      int y = (step + offsets[j]) % 8 - 1;
      px(y, cols[j], 3);
      px(y + 1, cols[j], 7);
    }
    for (int c = 1; c <= 11; c++) px(7, c, 2);
  } else if (flash == ACK) {                     // a ripple from the middle: "got it"
    float r = (now - flashSince) / 90.0;
    for (int row = 0; row < 8; row++)
      for (int col = 0; col < 13; col++) {
        float d = sqrt((col - 6) * (col - 6) + (row - 3.5) * (row - 3.5));
        if (fabs(d - r) < 0.7) px(row, col, 7);
      }
  } else if (flash == NOPE) {                    // a blinking X: "busy, not now"
    if ((now - flashSince) / 100 % 2 == 0)
      for (int i = 0; i <= 6; i++) { px(i, 3 + i); px(i, 9 - i); }
  } else if (mode == THINK) {                    // a faint track with a bright head and fading tail
    for (int i = 0; i < RING_N; i++) px(RING[i][0], RING[i][1], 1);
    for (int t = 0; t < 6; t++) {
      int i = ((step - t) % RING_N + RING_N) % RING_N;
      px(RING[i][0], RING[i][1], 7 - t);
    }
  } else if (mode == OK) {                       // the check mark draws itself
    for (int i = 0; i <= step && i < CHECK_N; i++) px(CHECK[i][0], CHECK[i][1]);
  } else if (mode == ALERT) {                    // a blinking exclamation mark
    if (step % 2 == 0) {
      for (int r = 0; r <= 4; r++) px(r, 6);
      px(6, 6); px(7, 6);
    }
  } else {                                       // IDLE: a calm pause sign
    for (int r = 1; r <= 6; r++) { px(r, 4, 3); px(r, 5, 3); px(r, 7, 3); px(r, 8, 3); }
  }
  matrix.draw(frame);
}

unsigned long framePeriod() {
  if (pumpZone) return 90;
  if (flash != NO_FLASH) return 30;
  if (mode == THINK || mode == OK) return 60;
  if (mode == ALERT) return 350;
  return 1000;
}

void setMode(Mode m) {
  if (m == THINK && mode == THINK) return;  // keep the circle turning smoothly
  mode = m;
  modeSince = millis();
  step = 0;
  if (m == ALERT) digitalWrite(PIN_LED_ALERT, HIGH);  // the red LED keeps the alert until a good result
  if (m == OK) digitalWrite(PIN_LED_ALERT, LOW);
  drawFrame(modeSince);
}

void startFlash(Flash f) {
  flash = f;
  flashSince = millis();
  drawFrame(flashSince);
}

// ---------------------------------------------------------------- pump

void pumpWrite(bool on) {
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
  digitalWrite(PIN_LED_WATER, on ? HIGH : LOW);
}

void stopPump() {
  pumpWrite(false);
  pumpZone = 0;
  modeSince = millis();  // the result shows its full time after the drops
  step = 0;
  drawFrame(modeSince);
}

// ---------------------------------------------------------------- functions Python can call

// {"ok":true,"zone":1,"seconds":30,"note":""}  or  {"ok":false,...,"note":"why"}
String reply(bool ok, int zone, int seconds, const String& note) {
  return String("{\"ok\":") + (ok ? "true" : "false") + ",\"zone\":" + zone +
         ",\"seconds\":" + seconds + ",\"note\":\"" + note + "\"}";
}

String water(int zone, int seconds) {
  long now = simMinutes();
  if (zone < 1 || zone > ZONES) return reply(false, zone, 0, "unknown zone " + String(zone));
  if (seconds <= 0) return reply(false, zone, 0, "nothing to do (0 s)");
  if (pumpZone) return reply(false, zone, 0, "pump is busy");
  if (tankEmpty) return reply(false, zone, 0, "water tank is empty");
  if (battery < BATTERY_FLOOR)
    return reply(false, zone, 0, "battery " + String(battery) + " % is below " + String(BATTERY_FLOOR) + " %");

  // Forget waterings older than 24 simulated hours.
  int kept = 0;
  for (int i = 0; i < historyCount[zone]; i++)
    if (now - history[zone][i] < 24L * 60) history[zone][kept++] = history[zone][i];
  historyCount[zone] = kept;

  if (kept > 0 && now - history[zone][kept - 1] < MIN_INTERVAL_MIN) {
    float hoursAgo = (now - history[zone][kept - 1]) / 60.0;
    return reply(false, zone, 0, "watered " + String(hoursAgo, 1) + " h ago, minimum is " + String(MIN_INTERVAL_MIN / 60) + " h");
  }
  if (kept >= MAX_PER_DAY) return reply(false, zone, 0, "already watered " + String(kept) + " times in 24 h");

  String note = "";
  if (seconds > MAX_PUMP_S) {
    note = "clamped from " + String(seconds) + " s to " + String(MAX_PUMP_S) + " s";
    seconds = MAX_PUMP_S;
  }
  history[zone][historyCount[zone]++] = now;

  pumpZone = zone;
  pumpOffAt = millis() + (unsigned long)seconds * 1000UL;
  pumpWrite(true);
  step = 0;
  drawFrame(millis());
  return reply(true, zone, seconds, note);
}

// Raw readings; python/sensors.py turns them into %, °C and "raining".
// {"a0":512,"a1":300,"a2":70,"a3":600,"a4":20,"button":3,"pump_zone":0,"sim_min":123}
String read_sensors() {
  return String("{\"a0\":") + analogRead(PIN_KNOB) +   // 10-bit (0-1023), measured on the board
         ",\"a1\":" + analogRead(PIN_SOIL) +
         ",\"a2\":" + analogRead(PIN_TEMP) +
         ",\"a3\":" + analogRead(PIN_LIGHT) +
         ",\"a4\":" + analogRead(PIN_STEAM) +
         ",\"button\":" + buttonPresses +
         ",\"pump_zone\":" + pumpZone +
         ",\"sim_min\":" + simMinutes() + "}";
}

bool set_sim_state(int newBattery, bool newTankEmpty) {
  battery = newBattery;
  tankEmpty = newTankEmpty;
  return true;
}

// "think", "ok", "alert", "idle", or "nope" (a quick X: Python is too busy for that request).
bool show(String icon) {
  if (icon == "nope") {
    startFlash(NOPE);
    return true;
  }
  thinkFromButton = false;
  setMode(icon == "think" ? THINK : icon == "ok" ? OK : icon == "alert" ? ALERT : IDLE);
  return true;
}

// ---------------------------------------------------------------- setup / loop

void setup() {
  pinMode(PIN_BUTTON, INPUT_PULLDOWN);  // reads "not pressed" even when no button is plugged in
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_LED_WATER, OUTPUT);
  pinMode(PIN_LED_ALERT, OUTPUT);
  pumpWrite(false);

  matrix.begin();
  matrix.setGrayscaleBits(3);
  setMode(IDLE);

  Bridge.begin();
  // provide_safe: these run in the main loop thread, so they can safely touch pins and the matrix.
  Bridge.provide_safe("water", water);
  Bridge.provide_safe("read_sensors", read_sensors);
  Bridge.provide_safe("set_sim_state", set_sim_state);
  Bridge.provide_safe("show", show);
}

void loop() {
  // Never block here: Bridge calls are served between loop() runs.
  unsigned long now = millis();

  if (pumpZone && (long)(now - pumpOffAt) >= 0) stopPump();

  // Count button presses (with 50 ms debounce). While Gemma is thinking a press is
  // ignored - a check takes minutes - and the X says so straight away.
  bool down = digitalRead(PIN_BUTTON) == BUTTON_PRESSED;
  if (down != buttonWasDown && now - buttonChangedAt > 50) {
    buttonChangedAt = now;
    buttonWasDown = down;
    if (down && mode == THINK) {
      startFlash(NOPE);
    } else if (down) {
      buttonPresses++;
      setMode(THINK);
      thinkFromButton = true;
      startFlash(ACK);
    }
  }

  // The matrix.
  if (flash != NO_FLASH && now - flashSince > FLASH_MS) {
    flash = NO_FLASH;
    drawFrame(now);
  }
  if (thinkFromButton && now - modeSince > BUTTON_WAIT_MS) {  // Python never answered (app not running?)
    thinkFromButton = false;
    setMode(IDLE);
  }
  if ((mode == OK || mode == ALERT) && !pumpZone && now - modeSince > RESULT_MS) setMode(IDLE);
  if (now - lastFrame >= framePeriod()) {
    lastFrame = now;
    step++;
    drawFrame(now);
  }
}
