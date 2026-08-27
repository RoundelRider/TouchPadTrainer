#include <Wire.h>
/*
#include <SPI.h>
#ifndef __ADAFRUIT_CAP1188_H__
  #include <Adafruit_CAP1188.h>
  #define __ADAFRUIT_CAP1188_H__
#endif
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
*/
#include <Adafruit_MPR121.h>

#define TOUCH_THRESHOLD 20
#define RELEASE_THRESHOLD 10
#define PADS_PER_CAP_CONTROLLER 12


class CapTouch {
public:
  CapTouch(uint8_t pads_per_controller);
  virtual ~CapTouch() {}

  virtual bool begin() {return false;}
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

/*
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
*/

class CapTouchMPR121: public CapTouch {
public:
  CapTouchMPR121(uint8_t address);
  virtual ~CapTouchMPR121();

  virtual bool begin();
  virtual void clear();
  virtual uint16_t touched(void);
  
protected:
  Adafruit_MPR121 *mpr121;
  uint8_t i2c_addr;
};