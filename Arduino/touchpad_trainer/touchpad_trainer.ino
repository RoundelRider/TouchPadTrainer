/**
 * Hand-Eye Coordination Training Pad Controller
 *
 * Hardware:
 *   - Arduino Nano
 *   - MPR121 Capacitive Touch Controller (I2C: SDA=A4, SCL=A5, IRQ=D2)
 *   - 12 touch pads with addressable RGB LEDs (WS2812B on D6)
 *
 * Serial Protocol (115200 baud):
 *   PC -> Arduino:
 *     START <duration_sec> <speed_ms> <type>
 *       type: SIMPLE | SELECTIVE
 *     STOP
 *
 *   Arduino -> PC (during routine):
 *     READY
 *     PAD <pad_id> <start_time_ms> <color>        (color: WHITE|GREEN|RED)
 *     TOUCH <pad_id> <reaction_time_ms> <correct>  (correct: 1|0)
 *     MISS <pad_id>                                (no touch before next pad)
 *     END <total_pads> <hits> <misses> <false_touches>
 *     ERROR <message>
 */

#include <Wire.h>
//#include <Adafruit_MPR121.h>
#include <SPI.h>
#include <Adafruit_CAP1188.h>
#include <Adafruit_NeoPixel.h>
#include "TrainerPanel.h"

// Reset Pin is used for I2C or SPI
#define CAP1188_RESET  9

// CS pin is used for software or hardware SPI
#define CAP1188_CS  10
#define CAP1188_CS2  8

// These are defined for software SPI, for hardware SPI, check your 
// board's SPI pins in the Arduino documentation
#define CAP1188_MOSI  11
#define CAP1188_MISO  12
#define CAP1188_CLK  13

Adafruit_CAP1188 cap0 = Adafruit_CAP1188(CAP1188_CS, CAP1188_RESET);
Adafruit_CAP1188 cap1 = Adafruit_CAP1188(CAP1188_CS2, CAP1188_RESET);

uint16_t lastTouched1 = 0;
uint16_t lastTouched2 = 0;

#ifndef _BV
#define _BV(bit) (1 << (bit))
#endif

// ── Pin definitions ──────────────────────────────────────────────────────────
#define LED_PIN         6          // LED data pin
#define NUM_PADS        16
#define LEDS_PER_PAD    7

// ── NeoPixel setup ───────────────────────────────────────────────────────────
Adafruit_NeoPixel led_array(NUM_PADS * LEDS_PER_PAD, LED_PIN, NEO_GRB + NEO_KHZ800);

// ── MPR121 setup ─────────────────────────────────────────────────────────────
//Adafruit_MPR121 cap0 = Adafruit_MPR121();
//Adafruit_MPR121 cap1 = Adafruit_MPR121();

#define PADS_PER_CAP_CONTROLLER 8
#define TOUCH_THRESHOLD 16
#define RELEASE_THRESHOLD 10


// Keeps track of the last pins touched
// so we know when buttons are 'released'
uint16_t cap0LastTouch = 0;
uint16_t cap1LastTouch = 0;

// ── Trainer instantiation  ────────────────────────────────────────────────────
TrainerPanel trainer(NUM_PADS, LEDS_PER_PAD, &led_array);

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

  // test leds
  led_array.setPixelColor(0, led_array.Color(255, 255, 255));
  led_array.show();

  /*
  // MPR121 board 0 init
  if (!cap0.begin(0x5A)) {
    Serial.println(F("ERROR MPR121 board 0 not found"));
    while (true);             // halt – hardware missing
  }
  cap0.setAutoconfig(true);
  cap0.setThresholds(TOUCH_THRESHOLD, RELEASE_THRESHOLD);
  Serial.println("MPR121 board 0 found and Initialized");
  */

  // MPR121 board 1 init
  /*
  if (!cap1.begin(0x5A)) {
    Serial.println(F("ERROR MPR121 board 1 not found"));
    while (true);             // halt – hardware missing
  }
  cap1.setAutoconfig(true);
  cap1.setThresholds(TOUCH_THRESHOLD, RELEASE_THRESHOLD);
  Serial.println("MPR121 board 1 found and Initialized");
  */

  // CAP1188 setup
  if (!cap0.begin()) {
    Serial.println("CAP1188 1 not found");
    while (1);
  }
  Serial.println("CAP1188 1 found!");
  cap0.writeRegister(CAP1188_LEDLINK, 0);

  if (!cap1.begin()) {
    Serial.println("CAP1188 2 not found");
    while (1);
  }
  Serial.println("CAP1188 2 found!");
  cap1.writeRegister(CAP1188_LEDLINK, 0);

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

    // check for a touch
    uint32_t now = millis();
    uint16_t touch = cap0.touched();
    if (touch != cap0LastTouch) {
      for (uint8_t i=0; i<12; i++) {
        // it if *is* touched and *wasnt* touched before, alert!
        if ((touch & _BV(i)) && !(cap0LastTouch & _BV(i)) ) {
          Serial.print("Board 0 pad "); Serial.print(i); Serial.println(" touched");
          trainer.Touch(i, now);
        }
        // if it *was* touched and now *isnt*, alert!
        if (!(touch & _BV(i)) && (cap0LastTouch & _BV(i)) ) {
          //Serial.print("Board 0 pad "); Serial.print(i); Serial.println(" released");
        }
      }
      
      // reset our state
      cap0LastTouch = touch;
    }
    touch = cap1.touched();
    if (touch != cap1LastTouch) {
      for (uint8_t i=0; i<12; i++) {
        // it if *is* touched and *wasnt* touched before, alert!
        if ((touch & _BV(i)) && !(cap1LastTouch & _BV(i))) {
          Serial.print("Board 1 pad "); Serial.print(i); Serial.println(" touched");
          trainer.Touch(PADS_PER_CAP_CONTROLLER + i, now);
        }
        // if it *was* touched and now *isnt*, alert!
        if (!(touch & _BV(i)) && (cap1LastTouch & _BV(i)) ) {
          Serial.print("Board 1 pad "); Serial.print(i); Serial.println(" released");
        }
      }
      
      // reset our state
      cap1LastTouch = touch;
    }
  }
  delay(5);
}
