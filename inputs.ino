#include <Arduino_LSM9DS1.h>
#include <PDM.h>

#define LIGHT_PIN A6

short sampleBuffer[256];
volatile int samplesRead = 0;

float soundLevel = 0;

// thresholds
const int LIGHT_CHANGE_THRESHOLD = 180;   // detect big on/off jump
const float ACCEL_THRESHOLD = 1.2;        // was 1.8
const float GYRO_THRESHOLD = 120.0;       // was 220
const float SOUND_THRESHOLD = 300.0;      // was 1000+
const float MAGNETIC_THRESHOLD = 60.0;    // was 120

unsigned long lastEventTime = 0;
const unsigned long COOLDOWN_MS = 1500;
int prevLightValue = -1;

void onPDMdata() {
  int bytesAvailable = PDM.available();

  if (bytesAvailable > sizeof(sampleBuffer)) {
    bytesAvailable = sizeof(sampleBuffer);
  }

  PDM.read(sampleBuffer, bytesAvailable);
  samplesRead = bytesAvailable / 2;
}

void setup() {
  Serial.begin(9600);
  delay(1500);

  IMU.begin();

  PDM.onReceive(onPDMdata);
  PDM.begin(1, 16000);

  Serial.println("{\"status\":\"ready\"}");
}

void loop() {
  int lightValue = analogRead(LIGHT_PIN);

  float accelMag = 0;
  float gyroMag = 0;
  float magneticMag = 0;

  float ax, ay, az;
  if (IMU.accelerationAvailable()) {
    IMU.readAcceleration(ax, ay, az);
    accelMag = sqrt(ax * ax + ay * ay + az * az);
  }

  float gx, gy, gz;
  if (IMU.gyroscopeAvailable()) {
    IMU.readGyroscope(gx, gy, gz);
    gyroMag = sqrt(gx * gx + gy * gy + gz * gz);
  }

  float mx, my, mz;
  if (IMU.magneticFieldAvailable()) {
    IMU.readMagneticField(mx, my, mz);
    magneticMag = sqrt(mx * mx + my * my + mz * mz);
  }

  if (samplesRead > 0) {
    long sum = 0;
    for (int i = 0; i < samplesRead; i++) {
      sum += abs(sampleBuffer[i]);
    }
    soundLevel = (float)sum / samplesRead;
    samplesRead = 0;
  }

  bool lightTriggered = false;
  if (prevLightValue >= 0) {
    lightTriggered = abs(lightValue - prevLightValue) >= LIGHT_CHANGE_THRESHOLD;
  }
  prevLightValue = lightValue;
  bool motionTriggered = accelMag > ACCEL_THRESHOLD;
  bool gyroTriggered = gyroMag > GYRO_THRESHOLD;
  bool soundTriggered = soundLevel > SOUND_THRESHOLD;
  bool magneticTriggered = magneticMag > MAGNETIC_THRESHOLD;

  bool anyTriggered =
    lightTriggered ||
    motionTriggered ||
    gyroTriggered ||
    soundTriggered ||
    magneticTriggered;

  if (anyTriggered && millis() - lastEventTime > COOLDOWN_MS) {
    lastEventTime = millis();

    Serial.print("{\"event\":1");

    Serial.print(",\"light_triggered\":");
    Serial.print(lightTriggered ? 1 : 0);

    Serial.print(",\"motion_triggered\":");
    Serial.print(motionTriggered ? 1 : 0);

    Serial.print(",\"gyro_triggered\":");
    Serial.print(gyroTriggered ? 1 : 0);

    Serial.print(",\"sound_triggered\":");
    Serial.print(soundTriggered ? 1 : 0);

    Serial.print(",\"magnetic_triggered\":");
    Serial.print(magneticTriggered ? 1 : 0);

    Serial.print(",\"light\":");
    Serial.print(lightValue);

    Serial.print(",\"accel\":");
    Serial.print(accelMag, 3);

    Serial.print(",\"gyro\":");
    Serial.print(gyroMag, 3);

    Serial.print(",\"sound\":");
    Serial.print(soundLevel, 2);

    Serial.print(",\"magnetic\":");
    Serial.print(magneticMag, 3);

    // Arduino_LSM9DS1 has no die-temp API; backend skips z-score when null.
    Serial.print(",\"temperature_c\":null");
    Serial.print(",\"pressure\":null");

    Serial.println("}");
  }
}