#include "CapTouch.h"

CapTouch::CapTouch(uint8_t pads_per_controller): 
  initialized(false),
  last_touch(0),
  pads_per_controller(pads_per_controller)
{
}

CapTouch1188::CapTouch1188(uint8_t i2caddr, uint8_t reset_pin):
  CapTouch(8),
  cap1188(NULL),
  i2c_addr(i2caddr)
{
  cap1188 = new Adafruit_CAP1188(reset_pin);
}

CapTouch1188::~CapTouch1188() {
  if (cap1188 != NULL) {
    delete cap1188;
    cap1188 = NULL;
  }
}

bool CapTouch1188::begin() {
  if (cap1188 && cap1188->begin(i2c_addr)) {
    initialized = true;
    cap1188->writeRegister(0x1F, 0x5F);
    return true;
  }
  else {
    initialized = false;
  }
  return false;
}

void CapTouch1188::clear() {
  last_touch = cap1188->touched();
}

uint16_t CapTouch1188::touched(void) {
  last_touch = cap1188->touched();
  return last_touch;
}

CapTouchMPR121::CapTouchMPR121(uint8_t address, uint8_t touchThreshold, uint8_t releaseThreshold):
  CapTouch(12),
  mpr121(NULL),
  i2c_addr(address),
  touch_threshold(touchThreshold),
  release_threshold(release_threshold)
{
  mpr121 = new Adafruit_MPR121();
}

CapTouchMPR121::~CapTouchMPR121() {
  if (mpr121) {
    delete mpr121;
    mpr121 = NULL;
  }
}

bool CapTouchMPR121::begin() {
  if (mpr121) {
    if (mpr121->begin(i2c_addr)) {
      mpr121->setAutoconfig(true);
      mpr121->setThresholds(touch_threshold, release_threshold);
      initialized = true;
      return true;
    }
    else {
      initialized = false;
    }
  }
  return false;
}

void CapTouchMPR121::clear() {
  last_touch = mpr121->touched();
}

uint16_t CapTouchMPR121::touched(void) {
  last_touch = mpr121->touched();
  return last_touch;
}
