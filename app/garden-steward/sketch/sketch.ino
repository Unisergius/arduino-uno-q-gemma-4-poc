// Garden Steward - microcontroller side (STM32U585).
//
// The MCU owns everything physical: sensors, the "pump" and the LED matrix.
// It also enforces the SAFETY LIMITS. Gemma (on the Linux side) can only *ask*
// to water; this sketch decides whether that is allowed. Keep the limits in sync
// with python/config.py.
//
// Paper Garden: no real pump. Pins 2 and 3 drive an LED or a relay module for
// zones 1 and 2, a Modulino Opto Relay clicks if one is plugged in, and the
// LED matrix shows water drops.

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <Arduino_Modulino.h>

// ---- Safety limits (same values as python/config.py) ----
const int MAX_PUMP_S = 60;                 // longest single watering, seconds
const long MIN_INTERVAL_MIN = 4L * 60;     // per zone, simulated minutes
const int MAX_PER_DAY = 3;                 // per zone, per 24 simulated hours
const int BATTERY_FLOOR = 20;              // %, no watering below this

// Simulated time: 1 real second = 1 simulated minute (TIME_SCALE = 60).
// The intervals above are measured on this scaled clock. Use 1 for a real garden.
const long TIME_SCALE = 60;

const int ZONES = 2;
const int PUMP_PIN[ZONES + 1] = {-1, 2, 3};  // index 0 unused; zone 1 -> pin 2, zone 2 -> pin 3

Arduino_LED_Matrix matrix;
ModulinoThermo thermo;
ModulinoPressure barometer;
ModulinoOptoRelay relay;
bool hasThermo = false, hasPressure = false, hasRelay = false;

// Simulated battery and tank, sent by Python. On a real garden these would be read
// from a battery monitor and a float switch instead.
int battery = 100;
bool tankEmpty = false;

// Watering history per zone (simulated minutes), newest last.
long history[ZONES + 1][MAX_PER_DAY];
int historyCount[ZONES + 1] = {0};

int pumpZone = 0;                // 0 = pump off
unsigned long pumpOffAt = 0;
unsigned long lastAnim = 0;
bool animFrame = false;

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
    for (int r = 0; r <= 4; r++) { px(r, 6); }
    px(6, 6); px(7, 6);
  } else {                                     // "ok": a check mark
    px(1, 11); px(2, 10); px(3, 9); px(4, 8); px(5, 7); px(6, 6); px(7, 5);
    px(4, 2); px(5, 3); px(6, 4);
  }
  matrix.draw(frame);
}

// ---------------------------------------------------------------- pump

void pumpWrite(int zone, bool on) {
  digitalWrite(PUMP_PIN[zone], on ? HIGH : LOW);
  digitalWrite(LED_BUILTIN, on ? LOW : HIGH);   // built-in LED is on when LOW
  if (hasRelay) { if (on) relay.on(); else relay.off(); }
}

void stopPump() {
  if (pumpZone) pumpWrite(pumpZone, false);
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
  pumpWrite(zone, true);
  drawIcon("water");
  return reply(true, zone, seconds, note);
}

// {"thermo":true,"temp_c":21.4,"humidity":48,"pressure":true,"pressure_hpa":1012.3,"pump_zone":0,"sim_min":123}
String read_sensors() {
  String json = "{\"thermo\":" + String(hasThermo ? "true" : "false");
  if (hasThermo) {
    json += ",\"temp_c\":" + String(thermo.getTemperature(), 1);
    json += ",\"humidity\":" + String(thermo.getHumidity(), 0);
  }
  json += ",\"pressure\":" + String(hasPressure ? "true" : "false");
  if (hasPressure) {
    json += ",\"pressure_hpa\":" + String(barometer.getPressure() * 10.0, 1);  // VERIFY: library returns kPa
  }
  json += ",\"pump_zone\":" + String(pumpZone) + ",\"sim_min\":" + String(simMinutes()) + "}";
  return json;
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
  for (int z = 1; z <= ZONES; z++) {
    pinMode(PUMP_PIN[z], OUTPUT);
    digitalWrite(PUMP_PIN[z], LOW);
  }
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // off

  matrix.begin();
  matrix.setGrayscaleBits(3);
  drawIcon("ok");

  // Optional Modulino sensors on the Qwiic connector. Missing ones are simply skipped.
  Modulino.begin();
  hasThermo = thermo.begin();
  hasPressure = barometer.begin();
  hasRelay = relay.begin();

  Bridge.begin();
  // provide_safe: these run in the main loop thread, so they can touch pins, I2C and the matrix.
  Bridge.provide_safe("water", water);
  Bridge.provide_safe("read_sensors", read_sensors);
  Bridge.provide_safe("set_sim_state", set_sim_state);
  Bridge.provide_safe("show", show);
}

void loop() {
  // Never block here: Bridge calls are served between loop() runs.
  if (pumpZone && (long)(millis() - pumpOffAt) >= 0) stopPump();
  if (pumpZone && millis() - lastAnim > 400) {
    lastAnim = millis();
    animFrame = !animFrame;
    drawIcon("water", animFrame);
  }
}
