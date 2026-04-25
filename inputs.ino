#include <Arduino_LSM9DS1.h>
#include <PDM.h>

#define LIGHT_PIN A6

short sampleBuffer[256];
volatile int samplesRead = 0;

unsigned long lastOutput = 0;
const unsigned long OUTPUT_INTERVAL_MS = 1000;

float peakAccel = 0;
float peakGyro = 0;
float peakMagnetic = 0;
float soundLevel = 0;

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

  if (!IMU.begin()) {
    Serial.println("{\"error\":\"IMU failed\"}");
  }

  PDM.onReceive(onPDMdata);

  if (!PDM.begin(1, 16000)) {
    Serial.println("{\"error\":\"PDM mic failed\"}");
  }

  Serial.println("{\"status\":\"ready\"}");
}

void loop() {
  // ----- accelerometer -----
  float ax, ay, az;
  if (IMU.accelerationAvailable()) {
    IMU.readAcceleration(ax, ay, az);
    float accelMag = sqrt(ax * ax + ay * ay + az * az);
    if (accelMag > peakAccel) peakAccel = accelMag;
  }

  // ----- gyroscope -----
  float gx, gy, gz;
  if (IMU.gyroscopeAvailable()) {
    IMU.readGyroscope(gx, gy, gz);
    float gyroMag = sqrt(gx * gx + gy * gy + gz * gz);
    if (gyroMag > peakGyro) peakGyro = gyroMag;
  }

  // ----- magnetometer -----
  float mx, my, mz;
  if (IMU.magneticFieldAvailable()) {
    IMU.readMagneticField(mx, my, mz);
    float magneticMag = sqrt(mx * mx + my * my + mz * mz);
    if (magneticMag > peakMagnetic) peakMagnetic = magneticMag;
  }

  // ----- microphone -----
  if (samplesRead > 0) {
    long sum = 0;

    for (int i = 0; i < samplesRead; i++) {
      sum += abs(sampleBuffer[i]);
    }

    soundLevel = (float)sum / samplesRead;
    samplesRead = 0;
  }

  // ----- light sensor -----
  int lightValue = analogRead(LIGHT_PIN);

  // ----- print once per second -----
  if (millis() - lastOutput >= OUTPUT_INTERVAL_MS) {
    lastOutput = millis();

    Serial.print("{\"light\":");
    Serial.print(lightValue);

    Serial.print(",\"sound_level\":");
    Serial.print(soundLevel, 2);

    Serial.print(",\"peak_accel\":");
    Serial.print(peakAccel, 3);

    Serial.print(",\"peak_gyro\":");
    Serial.print(peakGyro, 3);

    Serial.print(",\"peak_magnetic\":");
    Serial.print(peakMagnetic, 3);

    Serial.println("}");

    peakAccel = 0;
    peakGyro = 0;
    peakMagnetic = 0;
  }
}
