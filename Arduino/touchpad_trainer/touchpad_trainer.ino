/**
 * Hand-Eye Coordination Training Pad Controller
 *
 * Hardware:
 *   - Arduino Nano
 *   - MPR121 Capacitive Touch Controller (I2C: SDA=A4, SCL=A5, IRQ=D2)
 *   - 12 touch pads with addressable RGB LEDs (WS2812B on D6)
 *
 */

#include <Wire.h>
#include <Adafruit_NeoPixel.h>
#include "TrainerPanel.h"

// LED configuration
#define LED_PIN         6          // LED data pin
#define NUM_PADS        16
#define LEDS_PER_PAD    7

// translation rotation table
// physical layout:
//   0   1   2   3
//   7   6   5   4
//   8   9  10  11
//  15  14  13  12
// table index i = logical pad id, value = physical pad id
//uint16_t left_translation_table[] = {0, 1, 2, 3, 7, 6, 5, 4, 8, 9, 10, 11, 15, 14, 13, 12};
uint16_t bottom_translation_table[] = {3, 4, 11, 12, 2, 5, 10, 13, 1, 6, 9, 14, 0, 7, 8, 15};

// ── NeoPixel setup ───────────────────────────────────────────────────────────
Adafruit_NeoPixel led_array(NUM_PADS * LEDS_PER_PAD, LED_PIN, NEO_GRB + NEO_KHZ800);

// ── Trainer instantiation  ────────────────────────────────────────────────────
TrainerPanel trainer(NUM_PADS, LEDS_PER_PAD, &led_array, bottom_translation_table);

// ── Serial command parsing ────────────────────────────────────────────────────

void parseSerial() {
  static char buf[64];
  static uint8_t idx = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[idx] = '\0';
      idx = 0;
      trainer.ProcessCommand(buf);
      return;
    }
    if (idx < sizeof(buf) - 1) buf[idx++] = c;
  }
}

// ── Arduino setup ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  while (!Serial);

  // NeoPixel init
  led_array.begin();
  led_array.setBrightness(90);
  trainer.ClearLeds();

  if (!trainer.Start()) {
    Serial.println("ERROR starting training pad");
    while (true) {}
  }

  Serial.println(F("CONTROLLER_READY"));
}

// ── Arduino loop ──────────────────────────────────────────────────────────────
void loop() {
  // Always parse serial for commands
  parseSerial();

  if (!trainer.isTrainingActive()) {
    delay(10);
  }
  else {
    trainer.Tick();
    trainer.CheckTouch();
  }
  delay(5);
}
