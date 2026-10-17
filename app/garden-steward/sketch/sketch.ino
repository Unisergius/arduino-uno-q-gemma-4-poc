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

// Simulated battery and tank, sent by Python. On a real garden these would be read
// from a battery monitor and a float switch instead.
int battery = 100;
bool tankEmpty = false;

// Watering history per zone (simulated minutes), oldest first.
long history[ZONES + 1][MAX_PER_DAY];
int historyCount[ZONES + 1] = {0};

int pumpZone = 0;                // 0 = pump off
unsigned long pumpOffAt = 0;
unsigned long lastAnim = 0;
bool animFrame = false;

// Button presses are counted here; Python notices when the count goes up.
long buttonPresses = 0;
bool buttonWasDown = false;
unsigned long buttonChangedAt = 0;

uint8_t frame[8 * 13];

long simMinutes() {
  return (long)(millis() / 1000UL) * TIME_SCALE / 60;
}

// ---------------------------------------------------------------- LED matrix icons

void px(int row, int col) { frame[row * 13 + col] = 7; }

void drawIcon(const String& name, bool alt = false) {
  memset(frame, 0, sizeof(frame));
  if (name == "think") {                       // three dots
    for (int c : {3, 6, 9}) { px(3, c); px(4, c); }
  } else if (name == "water") {                // a drop, bouncing one row
    int o = alt ? 1 : 0;
    px(0 + o, 6); px(1 + o, 6);
    for (int c = 5; c <= 7; c++) px(2 + o, c);
    for (int r = 3; r <= 5; r++) for (int c = 4; c <= 8; c++) px(r + o, c);
    for (int c = 5; c <= 7; c++) px(6 + o, c);
  } else if (name == "alert") {                // exclamation mark
    for (int r = 0; r <= 4; r++) px(r, 6);
    px(6, 6); px(7, 6);
  } else {                                     // "ok": a check mark
    px(1, 11); px(2, 10); px(3, 9); px(4, 8); px(5, 7); px(6, 6); px(7, 5);
    px(4, 2); px(5, 3); px(6, 4);
  }
  matrix.draw(frame);
  digitalWrite(PIN_LED_ALERT, name == "alert" ? HIGH : LOW);
}

// ---------------------------------------------------------------- pump

void pumpWrite(bool on) {
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
  digitalWrite(PIN_LED_WATER, on ? HIGH : LOW);
}

void stopPump() {
  pumpWrite(false);
  pumpZone = 0;
  drawIcon("ok");
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
  drawIcon("water");
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

bool show(String icon) {
  if (!pumpZone) drawIcon(icon);   // while watering, the drops win
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
  drawIcon("ok");

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
  if (pumpZone && now - lastAnim > 400) {
    lastAnim = now;
    animFrame = !animFrame;
    drawIcon("water", animFrame);
  }

  // Count button presses (with 50 ms debounce).
  bool down = digitalRead(PIN_BUTTON) == BUTTON_PRESSED;
  if (down != buttonWasDown && now - buttonChangedAt > 50) {
    buttonChangedAt = now;
    buttonWasDown = down;
    if (down) buttonPresses++;
  }
}
