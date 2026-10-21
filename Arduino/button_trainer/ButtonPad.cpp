#include "ButtonPad.h"

ButtonPad::ButtonPad(uint8_t address, int sda, int scl):
  pcf(NULL),
  i2c_addr(address),
  initialized(false),
  pressed(false),
  last_switches(0),
  release_start_ms(0)
{
  // The interrupt pin is shared by every board and managed by TrainerPanel,
  // so the library is constructed without one.
  pcf = new PCF8574(address, sda, scl);
}

ButtonPad::~ButtonPad() {
  if (pcf) {
    delete pcf;
    pcf = NULL;
  }
}

bool ButtonPad::begin() {
  if (!pcf)
    return false;

  // pinMode must be set before begin(), which writes the initial pin state.
  uint8_t mode = BUTTON_ACTIVE_LOW ? INPUT_PULLUP : INPUT;
  pcf->pinMode(BUTTON_PIN_CENTER, mode);
  pcf->pinMode(BUTTON_PIN_CORNER_1, mode);
  pcf->pinMode(BUTTON_PIN_CORNER_2, mode);
  pcf->pinMode(BUTTON_PIN_CORNER_3, mode);
  pcf->pinMode(BUTTON_PIN_CORNER_4, mode);
  pcf->begin();

  // Confirm the chip ACKs its address rather than relying on begin()'s
  // return value, which differs between library versions.
  Wire.beginTransmission(i2c_addr);
  if (Wire.endTransmission() != 0) {
    Serial.print("ERROR: PCF8574 at address 0x"); Serial.print(i2c_addr, HEX); Serial.println(" not found");
    initialized = false;
    return false;
  }

  initialized = true;
  clear();
  return true;
}

uint8_t ButtonPad::read_switches() {
  if (!initialized)
    return 0;

  PCF8574::DigitalInput in = pcf->digitalReadAll();
  uint8_t level = (in.p0 ? _BV(0) : 0) |
                  (in.p1 ? _BV(1) : 0) |
                  (in.p2 ? _BV(2) : 0) |
                  (in.p3 ? _BV(3) : 0) |
                  (in.p4 ? _BV(4) : 0);
  uint8_t switches = BUTTON_ACTIVE_LOW ? ~level : level;
  return switches & BUTTON_PIN_MASK;
}

bool ButtonPad::update(uint32_t now) {
  uint8_t switches = read_switches();
  last_switches = switches;

  if (switches) {
    release_start_ms = 0;
    if (!pressed) {
      pressed = true;
      return true;
    }
  } else if (pressed) {
    if (release_start_ms == 0) {
      release_start_ms = now ? now : 1;  // 0 is reserved for "not releasing"
    } else if (now - release_start_ms >= BUTTON_RELEASE_DEBOUNCE_MS) {
      pressed = false;
      release_start_ms = 0;
    }
  }
  return false;
}

void ButtonPad::clear() {
  last_switches = read_switches();
  pressed = (last_switches != 0);
  release_start_ms = 0;
}
