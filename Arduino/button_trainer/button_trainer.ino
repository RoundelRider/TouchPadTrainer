/**
 * Hand-Eye Coordination Training Pad Controller -- button version
 *
 * Hardware:
 *   - Seeed Studio XIAO ESP32-C3
 *   - PCF8574 I/O expander per pad (I2C: SDA=D4, SCL=D5), read with the
 *     "PCF8574 library" by Renzo Mischianti
 *       P0      = center switch
 *       P1..P4  = outer ring corner switches
 *     Pressing the center or any corner switch counts as a touch of the pad.
 *   - PCF8574 INT (open drain, active low) on D2; shared by all boards
 *   - Addressable RGB LED array (WS2812B) on D3
 *
 * Speaks the same serial protocol as the capacitive touchpad_trainer sketch,
 * so the App works with either board. CAPON/CAPOFF start and stop the
 * PCF8574 boards instead of switching MPR121 power.
 */

#include <Wire.h>
#include <Adafruit_NeoPixel.h>
#include "TrainerPanel.h"

// Pin configuration (XIAO ESP32-C3)
#define I2C_SDA_PIN     D4
#define I2C_SCL_PIN     D5
#define BUTTON_INT_PIN  D2         // PCF8574 interrupt
#define LED_PIN         D3         // LED data pin

// Pad configuration
#define LEDS_PER_PAD    7

// I2C address of the PCF8574 for each physical pad, in pad order. The pad
// count is the number of boards. Address is 0x20 + A2..A0 for a PCF8574,
// or 0x38 + A2..A0 for a PCF8574A.
const uint8_t board_addresses[] = {0x20};
#define NUM_PADS        (sizeof(board_addresses) / sizeof(board_addresses[0]))

// Optional logical -> physical pad translation table (see touchpad_trainer).
// table index i = logical pad id, value = physical pad id. NULL = no translation.
uint16_t *translation_table = NULL;

// ── NeoPixel setup ───────────────────────────────────────────────────────────
Adafruit_NeoPixel led_array(NUM_PADS * LEDS_PER_PAD, LED_PIN, NEO_GRB + NEO_KHZ800);

// ── Trainer instantiation  ────────────────────────────────────────────────────
TrainerPanel trainer(NUM_PADS, LEDS_PER_PAD, &led_array,
                     board_addresses, NUM_PADS,
                     I2C_SDA_PIN, I2C_SCL_PIN, BUTTON_INT_PIN,
                     translation_table);

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
  // USB CDC: wait briefly for the host, but don't hang if none is attached.
  while (!Serial && millis() < 3000);

  // PCF8574 is limited to 100kHz I2C.
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);

  // NeoPixel init
  led_array.begin();
  led_array.setBrightness(10);
  trainer.ClearLeds();

  // Sets up the interrupt pin (boards are started by CAPON).
  trainer.Init();

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
    // Short delay while training; press timestamps come from the PCF8574
    // interrupt, so this doesn't add to the measured reaction time.
    delay(1);
  }
}
