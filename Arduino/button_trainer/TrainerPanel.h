#ifndef TRAINER_PANEL_H
#define TRAINER_PANEL_H

#include <Adafruit_NeoPixel.h>
#include "ButtonPad.h"

#define LED_COLOR_WHITE 0xFFFFFF
#define LED_COLOR_RED 0xFF0000
#define LED_COLOR_GREEN 0x00FF00
#define LED_COLOR_OFF 0x000000

// LED color names
#define LED_COLOR_NAME_WHITE "WHITE"
#define LED_COLOR_NAME_RED "RED"
#define LED_COLOR_NAME_GREEN "GREEN"

// Serial commands                                   params
#define CMD_CHECK_ORIENTATION "ORIENTATION"  // <ON/OFF>
#define CMD_PATTERN "PATTERN"                // <START/END>
#define CMD_TOUCH_SINGLE "SINGLE"            // <pad number> <color> <expect touch> <timeout>
#define CMD_TOUCH_DOUBLE "DOUBLE"            // <pad number 1> <pad number 2> <color> <expect touch> <timeout>
#define CMD_CANCEL "CANCEL"
#define CMD_VERSION "VERSION"
// The App sends CAPON/CAPOFF around every test. The names are kept for
// protocol compatibility with the capacitive version; here they attach and
// verify / release the PCF8574 button boards.
#define CMD_CAP_ON "CAPON"                   // start the PCF8574 boards and verify they all respond
#define CMD_CAP_OFF "CAPOFF"                 // stop reading the PCF8574 boards

#define MAX_CONCURRENT_PADS 2
#define MAX_BUTTON_BOARDS 16

// Re-read the boards at least this often while training, in case a PCF8574
// interrupt is missed (e.g. a change while the bus was being read).
#define BUTTON_POLL_INTERVAL_MS 20

class TrainerPanel {
public:
  // board_addresses[i] is the I2C address of the PCF8574 for physical pad i.
  // All boards share one open-drain interrupt line on interrupt_pin.
  TrainerPanel(uint16_t pads, uint16_t leds_per_pad, Adafruit_NeoPixel *led_array,
               const uint8_t *board_addresses, uint8_t board_count,
               int sda_pin, int scl_pin, uint8_t interrupt_pin,
               uint16_t *translation_table = NULL);
  ~TrainerPanel();

  void Init();
  void ProcessCommand(const char *cmd);

  void Tick();
  void CheckTouch();
  void Touch(uint16_t touchedPadId, uint32_t touchMs);

  bool isTrainingActive() {
    return trainingActive;
  }

  void ClearLeds(bool show = true);

protected:
  // new commands handlers
  void CheckOrientation(bool enable);
  void LedPatternStart();
  void LedPatternEnd();
  bool ButtonsOn();
  void ButtonsOff();
  void StartSingleTouch(int pad_number, uint32_t color, bool expect_touch, uint32_t timeout);
  void StartDoubleTouch(int pad_number_1, int pad_number_2, uint32_t color, bool expect_touch, uint32_t timeout);

  void FlashLeds(uint16_t count, uint32_t color);
  void SetLed(uint16_t pad, uint16_t index, uint32_t color, bool clear = true, bool show = true);
  void SetPadLeds(uint16_t pad, uint32_t color, bool clear = true, bool show = true);
  uint32_t GetLedColorFromString(char *color_string);

  void ClearTouch();

  void SendPadResult();

  uint16_t TranslatePad(uint16_t from_pad, bool reverse = false);

  static void OnButtonInterrupt();

  // physical configuration
  uint16_t pad_count;
  uint16_t leds_per_pad;
  Adafruit_NeoPixel *led_array;
  const uint8_t *board_addresses;
  uint8_t board_count;
  int sda_pin;
  int scl_pin;
  uint8_t interrupt_pin;
  ButtonPad *boards[MAX_BUTTON_BOARDS];
  uint32_t lastPollMs;

  // set by the PCF8574 interrupt; the time of the first edge since last read
  static volatile bool buttonInterrupt;
  static volatile uint32_t buttonInterruptMs;
  static portMUX_TYPE buttonInterruptMux;

  // translation
  uint16_t *translation_table;

  // pad information during training
  bool trainingActive;
  uint16_t activePadCount;
  uint16_t touchedPadCount;
  uint16_t padIds[MAX_CONCURRENT_PADS];
  uint32_t padStartMs;
  uint32_t padEndMs;
  uint32_t padTouchMs[MAX_CONCURRENT_PADS];
  bool padTouched[MAX_CONCURRENT_PADS];
  uint32_t padLedColor;
  bool padExpectTouch;
};

#endif
