#include <DHT.h>

const int TRIG_PIN = 9;
const int ECHO_PIN = 10;
const int DHT_PIN  = 2;

DHT dht(DHT_PIN, DHT11);

float readDistanceCm(float tempC) {
  float cm[5];
  int n = 0;
  float cmPerUs = (331.3f + 0.606f * tempC) / 10000.0f;
  for (int i = 0; i < 5; i++) {
    digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(4);
    digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    unsigned long us = pulseIn(ECHO_PIN, HIGH, 30000UL);
    if (us > 0) cm[n++] = us * cmPerUs / 2.0f;
    delay(60);
  }
  if (n == 0) return NAN;
  for (int i = 1; i < n; i++) {
    float k = cm[i];
    int j = i - 1;
    while (j >= 0 && cm[j] > k) { cm[j + 1] = cm[j]; j--; }
    cm[j + 1] = k;
  }
  return cm[n / 2];
}

void printField(const char* name, float v) {
  Serial.print("\"");
  Serial.print(name);
  Serial.print("\":");
  if (isnan(v)) Serial.print("null");
  else Serial.print(v, 2);
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  dht.begin();
}

void loop() {
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  float d = readDistanceCm(isnan(t) ? 20.0f : t);
  Serial.print("{");
  printField("temp_c", t);  Serial.print(",");
  printField("rh", h);      Serial.print(",");
  printField("dist_cm", d);
  Serial.println("}");
  delay(2000);
}
