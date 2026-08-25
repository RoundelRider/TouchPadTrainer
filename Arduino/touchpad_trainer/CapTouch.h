#include <Wire.h>
#include <SPI.h>
#ifndef __ADAFRUIT_CAP1188_H__
  #include <Adafruit_CAP1188.h>
  #define __ADAFRUIT_CAP1188_H__
#endif
#include <Adafruit_MPR121.h>

class CapTouch {
public:
  CapTouch(uint8_t pads_per_controller);
  virtual ~CapTouch() {}

  virtual void clear() {return;}
  virtual uint16_t touched(void) { return 0; }
  bool is_initialized() { return initialized; }
  uint8_t pad_count() { return pads_per_controller; }
  uint8_t controller_pads() { return pads_per_controller; }
  uint16_t get_last_touch() { return last_touch; }

protected:
  bool initialized;
  uint16_t last_touch;
  uint8_t pads_per_controller;
};

class CapTouch1188: public CapTouch {
public:
  CapTouch1188(uint8_t i2caddr = CAP1188_I2CADDR, uint8_t reset_pin = -1);
  virtual ~CapTouch1188();

  virtual uint16_t touched(void);
  bool begin();
  virtual void clear();
protected:
  Adafruit_CAP1188 *cap1188;
  uint8_t i2c_addr;
};

class CapTouchMPR121: public CapTouch {
public:
  CapTouchMPR121(uint8_t address, uint8_t touchThreshold, uint8_t releaseThreshold);
  virtual ~CapTouchMPR121();

  bool begin();
  virtual void clear();
  virtual uint16_t touched(void);
  
protected:
  Adafruit_MPR121 *mpr121;
  uint8_t i2c_addr;
  uint8_t touch_threshold;
  uint8_t release_threshold;
};