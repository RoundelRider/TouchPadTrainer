#ifndef BUTTON_PAD_H
#define BUTTON_PAD_H

#include <Arduino.h>
#include <Wire.h>
#include <PCF8574.h>   // "PCF8574 library" by Renzo Mischianti

// PCF8574 inputs used by a pad:
//   P0      = center switch
//   P1..P4  = outer ring corner switches
#define BUTTON_PIN_CENTER   P0
#define BUTTON_PIN_CORNER_1 P1
#define BUTTON_PIN_CORNER_2 P2
#define BUTTON_PIN_CORNER_3 P3
#define BUTTON_PIN_CORNER_4 P4
#define BUTTON_PIN_COUNT    5
#define BUTTON_PIN_MASK     0x1F   // bits P0..P4

// Switches are wired between the PCF8574 pin and GND, so a pressed switch
// reads LOW (the PCF8574's quasi-bidirectional pins provide a weak pull-up).
// Set to 0 if the switches pull the pin HIGH against an external pull-down.
#define BUTTON_ACTIVE_LOW 1

// A press registers on the first edge so the reaction time isn't delayed,
// but a release only registers once all switches have read released for this
// long. That absorbs contact bounce on both press and release.
#define BUTTON_RELEASE_DEBOUNCE_MS 30

// A single pad: one PCF8574 with a center switch and four corner switches.
class ButtonPad {
public:
  ButtonPad(uint8_t address, int sda, int scl);
  ~ButtonPad();

  bool begin();
  bool is_initialized() { return initialized; }
  uint8_t address() { return i2c_addr; }

  // Read the PCF8574 and return a bitmask of pressed switches
  // (bit n set = Pn pressed, limited to BUTTON_PIN_MASK).
  uint8_t read_switches();

  // Read the switches and update the debounced pad state.
  // Returns true if the pad transitioned from released to pressed.
  bool update(uint32_t now);

  // Re-sync the debounced state to the switches as they are right now,
  // so a switch already held down isn't reported as a new press.
  void clear();

  bool is_pressed() { return pressed; }
  bool release_pending() { return release_start_ms != 0; }
  uint8_t get_last_switches() { return last_switches; }

protected:
  PCF8574 *pcf;
  uint8_t i2c_addr;
  bool initialized;

  bool pressed;              // debounced pad state (any switch pressed)
  uint8_t last_switches;     // raw switch bitmask from the last read
  uint32_t release_start_ms; // when all switches first read released, 0 = not releasing
};

#endif
