/*
 * HomePulse AI — Arduino Sensor Sketch
 *
 * Sensors:
 *   - Sound/microphone      → A0 (analog)
 *   - Temperature (DHT22)   → D2 (digital)
 *   - Hall effect (magnetic)→ D3 (digital, INPUT_PULLUP)
 *   - MPU6050 accelerometer → I2C (SDA=A4, SCL=A5)
 *   - Pressure (analog)     → A1 (optional)
 *
 * Output: JSON over serial at 9600 baud every 5 seconds
 *
 * Dependencies (install via Arduino Library Manager):
 *   - DHT sensor library by Adafruit
 *   - Adafruit Unified Sensor
 *   - MPU6050 by Electronic Cats (or Adafruit MPU6050)
 *   - ArduinoJson by Benoit Blanchon
 */

#include <DHT.h>
#include <Wire.h>
#include <MPU6050.h>
#include <ArduinoJson.h>

// ── Pin definitions ─────────────────────────────────────────────────────────
#define SOUND_PIN     A0
#define PRESSURE_PIN  A1
#define DHT_PIN       2
#define DHT_TYPE      DHT22
#define MAGNETIC_PIN  3

// ── Instances ────────────────────────────────────────────────────────────────
DHT dht(DHT_PIN, DHT_TYPE);
MPU6050 mpu;

// ── Timing ───────────────────────────────────────────────────────────────────
const unsigned long INTERVAL_MS = 5000;
unsigned long lastSend = 0;

void setup() {
  Serial.begin(9600);
  dht.begin();

  pinMode(MAGNETIC_PIN, INPUT_PULLUP);

  Wire.begin();
  mpu.initialize();
  if (!mpu.testConnection()) {
    // MPU6050 not found — will send 0s for accel
  }

  delay(2000); // allow sensors to stabilise
}

void loop() {
  unsigned long now = millis();
  if (now - lastSend < INTERVAL_MS) return;
  lastSend = now;

  // ── Read sensors ───────────────────────────────────────────────────────────
  int soundRaw     = analogRead(SOUND_PIN);
  int pressureRaw  = analogRead(PRESSURE_PIN);
  int magneticState = digitalRead(MAGNETIC_PIN) == LOW ? 0 : 1; // 0=closed, 1=open

  float tempC = dht.readTemperature();
  if (isnan(tempC)) tempC = -999.0;   // sentinel for failed read

  int16_t ax, ay, az;
  mpu.getAcceleration(&ax, &ay, &az);
  // Convert raw (±2g range, 16384 LSB/g) to m/s²
  float accelX = ax / 16384.0 * 9.81;
  float accelY = ay / 16384.0 * 9.81;
  float accelZ = az / 16384.0 * 9.81;

  // ── Build JSON ─────────────────────────────────────────────────────────────
  StaticJsonDocument<256> doc;
  doc["sound_level"]   = soundRaw;
  doc["temperature_c"] = tempC;
  doc["magnetic_state"]= magneticState;
  doc["accel_x"]       = accelX;
  doc["accel_y"]       = accelY;
  doc["accel_z"]       = accelZ;
  doc["pressure"]      = pressureRaw;

  serializeJson(doc, Serial);
  Serial.println();
}
