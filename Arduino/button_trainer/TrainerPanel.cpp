#include "TrainerPanel.h"

#ifndef _BV
#define _BV(bit) (1 << (bit))
#endif

volatile bool TrainerPanel::buttonInterrupt = false;
volatile uint32_t TrainerPanel::buttonInterruptMs = 0;
// noInterrupts()/interrupts() are no-ops on the ESP32 core, so the flag and
// timestamp shared with the ISR are guarded with a critical section instead.
portMUX_TYPE TrainerPanel::buttonInterruptMux = portMUX_INITIALIZER_UNLOCKED;

void IRAM_ATTR TrainerPanel::OnButtonInterrupt() {
  // Keep the timestamp of the first edge so the reaction time reflects when
  // the switch closed, not when the main loop got around to reading it.
  portENTER_CRITICAL_ISR(&buttonInterruptMux);
  if (!buttonInterrupt) {
    buttonInterruptMs = millis();
    buttonInterrupt = true;
  }
  portEXIT_CRITICAL_ISR(&buttonInterruptMux);
}

TrainerPanel::TrainerPanel(uint16_t pads, uint16_t leds_per_pad, Adafruit_NeoPixel *led_array,
                           const uint8_t *board_addresses, uint8_t board_count,
                           int sda_pin, int scl_pin, uint8_t interrupt_pin,
                           uint16_t *translation_table)
  : pad_count(pads),
    leds_per_pad(leds_per_pad),
    led_array(led_array),
    board_addresses(board_addresses),
    board_count(min(board_count, (uint8_t)MAX_BUTTON_BOARDS)),
    sda_pin(sda_pin),
    scl_pin(scl_pin),
    interrupt_pin(interrupt_pin),
    lastPollMs(0),
    translation_table(translation_table) {
  memset(boards, 0, sizeof(boards));
  trainingActive = false;
}

TrainerPanel::~TrainerPanel() {
  ButtonsOff();
}


void TrainerPanel::Init() {
  ClearLeds(true);

  // The PCF8574 INT output is open drain and active low, so the pin needs a
  // pull-up. The interrupt is only attached while the boards are on (CAPON).
  pinMode(interrupt_pin, INPUT_PULLUP);
}

bool TrainerPanel::ButtonsOn() {
  ButtonsOff();

  // Probe every board unconditionally so a failure on one doesn't stop the
  // others from being verified and logged.
  bool ok = true;
  for (uint8_t i = 0; i < board_count; i++) {
    boards[i] = new ButtonPad(board_addresses[i], sda_pin, scl_pin);
    if (!boards[i]->begin())
      ok = false;
  }

  if (!ok) {
    // Don't leave the boards in a half-initialised state -- the next CAPON
    // attempt starts from a clean slate.
    ButtonsOff();
    return false;
  }

  buttonInterrupt = false;
  attachInterrupt(digitalPinToInterrupt(interrupt_pin), OnButtonInterrupt, FALLING);
  return true;
}

void TrainerPanel::ButtonsOff() {
  detachInterrupt(digitalPinToInterrupt(interrupt_pin));
  buttonInterrupt = false;
  for (uint8_t i = 0; i < MAX_BUTTON_BOARDS; i++) {
    if (boards[i] != NULL) {
      delete boards[i];
      boards[i] = NULL;
    }
  }
}

void TrainerPanel::ProcessCommand(const char *cmd) {
  /*
    Program Requirements
    1) Check orientation on.  The #1 pad will be lit in a specified color so
       that the user can verify pad orientation and pad number in the main
       program.
    2) Check orientation off.  Turns off all leds.
    3) Test start pattern.  The pad flashes green to indicate that the test
       is about to start.
    4) Test end pattern.  Like the start pattern, the pad flashes red to
       indicate the test is complete.
    5) Single touch.  Set the leds on the the specified pad number to the
       indicated color (may be white, green or red), and measure the time until
       the pad is pressed from the time the leds are enabled.  The pad will
       time out according to the included timeout parameter.  Pressing the
       center switch or any corner switch counts as a touch.
    6) Dual touch.  Two pads are specified with the indicated color.  Both
       pads must be pressed to make a successful "expect touch" result.
    7) CAPON / CAPOFF.  CAPON starts the PCF8574 boards and verifies all are
       detected, replying "CAPON OK" or an ERROR line.  CAPOFF stops reading
       them.  Names are shared with the capacitive version so the App works
       with either board.
  */
  Serial.print("Processing command: ");
  Serial.println(cmd);
  if (strncmp(cmd, CMD_CHECK_ORIENTATION, strlen(CMD_CHECK_ORIENTATION)) == 0) {
    bool enable = false;
    char enable_str[10];
    if (sscanf(cmd + strlen(CMD_CHECK_ORIENTATION) + 1, "%9s", enable_str)) {
      enable = (strcmp(enable_str, "ON") == 0);
      CheckOrientation(enable);
    } else {
      Serial.println("Error: Invalid check orientation command parameters, expecting: <ON/OFF>");
    }
  } else if (strncmp(cmd, CMD_PATTERN, strlen(CMD_PATTERN)) == 0) {
    char pattern_str[10];
    if (sscanf(cmd + strlen(CMD_PATTERN) + 1, "%9s", pattern_str)) {
      if (strcmp(pattern_str, "START") == 0) {
        LedPatternStart();
      } else if (strcmp(pattern_str, "END") == 0) {
        LedPatternEnd();
      } else {
        Serial.println("ERROR: Invalid pattern command parameter.  Expected <START/END>");
      }
    } else {
      Serial.println("ERROR: Invalid pattern command parameter.  Expected <START/END>");
    }
  } else if (strncmp(cmd, CMD_TOUCH_SINGLE, strlen(CMD_TOUCH_SINGLE)) == 0) {
    // <pad number> <color> <expect touch> <timeout>
    int padNumber = -1;
    char colorStr[13];
    char expectTouchStr[7];
    unsigned long timeout = 0;
    if (sscanf(cmd + strlen(CMD_TOUCH_SINGLE) + 1, "%d %12s %6s %lu", &padNumber, colorStr, expectTouchStr, &timeout) == 4) {
      uint32_t color = GetLedColorFromString(colorStr);
      bool expectTouch = true;
      if (strcmp(expectTouchStr, "FALSE") == 0)
        expectTouch = false;

      StartSingleTouch(padNumber, color, expectTouch, timeout);
    } else {
      Serial.print("ERROR: Invalid ");
      Serial.print(CMD_TOUCH_SINGLE);
      Serial.println(" command parameters. Expected: <pad number> <Color: WHITE|GREEN|RED> <ExpectTouch: TRUE|FALSE> <timeout ms>");
    }
  } else if (strncmp(cmd, CMD_TOUCH_DOUBLE, strlen(CMD_TOUCH_DOUBLE)) == 0) {
    // <pad number 1> <pad number 2> <color> <expect touch> <timeout>
    int padNumber1 = -1;
    int padNumber2 = -1;
    char colorStr[13];
    char expectTouchStr[7];
    unsigned long timeout = 0;
    if (sscanf(cmd + strlen(CMD_TOUCH_DOUBLE) + 1, "%d %d %12s %6s %lu", &padNumber1, &padNumber2, colorStr, expectTouchStr, &timeout) == 5) {
      uint32_t color = GetLedColorFromString(colorStr);
      bool expectTouch = true;
      if (strcmp(expectTouchStr, "FALSE") == 0)
        expectTouch = false;

      StartDoubleTouch(padNumber1, padNumber2, color, expectTouch, timeout);
    } else {
      Serial.print("ERROR: Invalid ");
      Serial.print(CMD_TOUCH_DOUBLE);
      Serial.println(" command parameters. Expected: <pad number 1> <pad number 2> <Color: WHITE|GREEN|RED> <ExpectTouch: TRUE|FALSE> <timeout ms>");
    }
  } else if (strncmp(cmd, CMD_CAP_ON, strlen(CMD_CAP_ON)) == 0) {
    if (ButtonsOn()) {
      Serial.println("CAPON OK");
    } else {
      Serial.println("ERROR: CAPON failed - PCF8574 button board(s) not detected");
    }
  } else if (strncmp(cmd, CMD_CAP_OFF, strlen(CMD_CAP_OFF)) == 0) {
    ButtonsOff();
    Serial.println("CAPOFF OK");
  } else if (strncmp(cmd, CMD_CANCEL, strlen(CMD_CANCEL)) == 0) {

  } else if (strncmp(cmd, CMD_VERSION, strlen(CMD_VERSION)) == 0) {
    Serial.println("VERSION 1.0");
  }
}

void TrainerPanel::Tick() {
  uint32_t now = millis();

  // determine if the pad has expired (wrap-safe comparison)
  if ((int32_t)(now - padEndMs) >= 0) {
    // pad expired with no touch
    SendPadResult();
  }
}

void TrainerPanel::CheckTouch() {
  uint32_t now = millis();

  // Only touch the I2C bus when something may have changed: the PCF8574
  // signalled a change, a release is still being debounced, or the safety
  // poll interval has elapsed.
  bool interrupted = false;
  uint32_t edgeMs = now;
  portENTER_CRITICAL(&buttonInterruptMux);
  if (buttonInterrupt) {
    interrupted = true;
    edgeMs = buttonInterruptMs;
    buttonInterrupt = false;
  }
  portEXIT_CRITICAL(&buttonInterruptMux);

  bool releasing = false;
  for (uint8_t i = 0; i < board_count; i++) {
    if (boards[i] && boards[i]->release_pending())
      releasing = true;
  }

  if (!interrupted && !releasing && (now - lastPollMs) < BUTTON_POLL_INTERVAL_MS)
    return;
  lastPollMs = now;

  for (uint8_t i = 0; i < board_count; i++) {
    ButtonPad *board = boards[i];
    if (board == NULL)
      continue;

    bool was_pressed = board->is_pressed();
    if (board->update(now)) {
      Serial.print("DEBUG: Pad ");
      Serial.print(i);
      Serial.print(" pressed, switches 0x");
      Serial.println(board->get_last_switches(), HEX);
      Touch(i, interrupted ? edgeMs : now);
    } else if (was_pressed && !board->is_pressed()) {
      Serial.print("DEBUG: Pad ");
      Serial.print(i);
      Serial.println(" released");
    }
  }
}

void TrainerPanel::Touch(uint16_t touchedPadId, uint32_t touchedMs) {
  // If the touch occurred before the pad start, then disregard
  if ((int32_t)(touchedMs - padStartMs) < 0)
    return;

  // Check to see if the pad was one of the active pads
  // and hasn't already been touched (if we're checking for multiple pads)
  for (int i = 0; i < activePadCount; i++) {
    if (padIds[i] == touchedPadId) {
      if (padTouched[i] == false) {
        touchedPadCount++;
        padTouchMs[i] = touchedMs;
        padTouched[i] = true;
        break;
      }
    }
  }

  // check to see if all pads have been touched
  if (touchedPadCount == activePadCount) {
    // Report touch completion
    SendPadResult();
  }
}

void TrainerPanel::ClearLeds(bool show) {
  led_array->clear();
  if (show) led_array->show();
}

void TrainerPanel::CheckOrientation(bool enable) {
  // if enable is true, light led 0 on logical pad 1 so orientation can be verified
  ClearLeds(false);
  if (enable) {
    // led 0 on pad 1
    SetLed(TranslatePad(0), 0, LED_COLOR_WHITE, false, false);
  }
  led_array->show();

  Serial.print(CMD_CHECK_ORIENTATION);
  Serial.print(" is ");
  Serial.println(enable ? "ON" : "OFF");
}

void TrainerPanel::LedPatternStart() {
  // Flash green leds
  FlashLeds(1, LED_COLOR_GREEN);
  Serial.println("PATTERN COMPLETE");
}

void TrainerPanel::LedPatternEnd() {
  FlashLeds(1, LED_COLOR_RED);
  Serial.println("PATTERN COMPLETE");
}

void TrainerPanel::StartSingleTouch(int pad_number, uint32_t color, bool expect_touch, uint32_t timeout) {
  Serial.print("StartSingleTouch pad:");
  Serial.print(pad_number);
  Serial.print(" color: ");
  Serial.print(color, HEX);
  Serial.print(" expect touch: ");
  Serial.print(expect_touch);
  Serial.print(" timeout ms: ");
  Serial.println(timeout);

  // translate pad number
  pad_number = TranslatePad(pad_number);

  // ignore any presses between pads
  ClearTouch();

  // initialize variables
  trainingActive = true;
  activePadCount = 1;
  touchedPadCount = 0;
  padIds[0] = pad_number;
  padIds[1] = 0;
  padStartMs = millis();
  padEndMs = padStartMs + timeout;
  padLedColor = color;
  padExpectTouch = expect_touch;
  memset(padTouchMs, 0, sizeof(padTouchMs));
  memset(padTouched, 0, sizeof(padTouched));

  // set the pad led
  SetPadLeds(pad_number, color);
}

void TrainerPanel::StartDoubleTouch(int pad_number_1, int pad_number_2, uint32_t color, bool expect_touch, uint32_t timeout) {
  Serial.print("StartDoubleTouch pad 1:");
  Serial.print(pad_number_1);
  Serial.print(" pad 2: ");
  Serial.print(pad_number_2);
  Serial.print(" color: ");
  Serial.print(color, HEX);
  Serial.print(" expect touch: ");
  Serial.print(expect_touch);
  Serial.print(" timeout ms: ");
  Serial.println(timeout);

  // translate pad numbers
  pad_number_1 = TranslatePad(pad_number_1);
  pad_number_2 = TranslatePad(pad_number_2);

  // ignore any presses between pads
  ClearTouch();

  // initialize variables
  trainingActive = true;
  activePadCount = 2;
  touchedPadCount = 0;
  padIds[0] = pad_number_1;
  padIds[1] = pad_number_2;
  padStartMs = millis();
  padEndMs = padStartMs + timeout;
  padLedColor = color;
  padExpectTouch = expect_touch;
  memset(padTouchMs, 0, sizeof(padTouchMs));
  memset(padTouched, 0, sizeof(padTouched));

  // set the pad led's
  SetPadLeds(pad_number_1, color, true, false);
  SetPadLeds(pad_number_2, color, false, true);
}

void TrainerPanel::FlashLeds(uint16_t count, uint32_t color) {
  for (int c = 0; c < count; c++) {
    led_array->clear();
    for (int i = 0; i < (pad_count * leds_per_pad); i++)
      led_array->setPixelColor(i, color);
    led_array->show();
    delay(500);

    led_array->clear();
    led_array->show();
    delay(500);
  }
}

void TrainerPanel::SetLed(uint16_t pad, uint16_t index, uint32_t color, bool clear, bool show) {
  uint16_t padLedIndex = pad * leds_per_pad;
  if (clear)
    led_array->clear();
  led_array->setPixelColor(padLedIndex + index, color);
  if (show)
    led_array->show();
}

void TrainerPanel::SetPadLeds(uint16_t pad, uint32_t color, bool clear, bool show) {
  // Set all pad LEDs to the specified color
  uint16_t padLedIndex = pad * leds_per_pad;
  if (clear) led_array->clear();
  for (int i = 0; i < leds_per_pad; i++) {
    led_array->setPixelColor(padLedIndex + i, color);
  }
  if (show) led_array->show();
}

void TrainerPanel::ClearTouch() {
  portENTER_CRITICAL(&buttonInterruptMux);
  buttonInterrupt = false;
  portEXIT_CRITICAL(&buttonInterruptMux);

  for (uint8_t i = 0; i < board_count; i++) {
    if (boards[i])
      boards[i]->clear();
  }
  lastPollMs = millis();
}

void TrainerPanel::SendPadResult() {
  // Send the following response:
  // SINGLE_PAD_RESULT <pad id> <touched> <response time>
  // DOUBLE_PAD_RESULT <pad 1 id> <pad 2 id> <touched> <response time>

  trainingActive = false;
  ClearLeds();

  // logical pad ids
  uint16_t logical_pad_0 = TranslatePad(padIds[0], true);
  uint16_t logical_pad_1 = TranslatePad(padIds[1], true);

  // result for a single pad
  if (activePadCount == 1) {
    // determine if the pad was touched, and if so calculate the reaction time
    bool pad_touched = padTouched[0];
    uint32_t reaction_time = 0;
    if (pad_touched) {
      reaction_time = padTouchMs[0] - padStartMs;
    }

    Serial.print("SINGLE_PAD_RESULT ");
    Serial.print(logical_pad_0);
    Serial.print(pad_touched ? " TRUE " : " FALSE ");
    Serial.println(reaction_time);
  }
  // result for a double pad
  else {
    // determine if both pads were touched
    bool pad_touched = padTouched[0] && padTouched[1];
    uint32_t reaction_time = 0;
    if (pad_touched)
      reaction_time = max(padTouchMs[0], padTouchMs[1]) - padStartMs;

    Serial.print("DOUBLE_PAD_RESULT ");
    Serial.print(logical_pad_0);
    Serial.print(" ");
    Serial.print(logical_pad_1);
    Serial.print(pad_touched ? " TRUE " : " FALSE ");
    Serial.println(reaction_time);
  }
}

uint32_t TrainerPanel::GetLedColorFromString(char *color_string) {
  uint32_t color = LED_COLOR_OFF;  // default to off
  if (strcmp(color_string, LED_COLOR_NAME_RED) == 0)
    color = LED_COLOR_RED;
  else if (strcmp(color_string, LED_COLOR_NAME_GREEN) == 0)
    color = LED_COLOR_GREEN;
  else if (strcmp(color_string, LED_COLOR_NAME_WHITE) == 0)
    color = LED_COLOR_WHITE;
  return color;
}

uint16_t TrainerPanel::TranslatePad(uint16_t from_pad, bool reverse) {
  if (translation_table && from_pad < pad_count) {
    if (reverse) {
      for (uint16_t i = 0; i < pad_count; i++) {
        if (translation_table[i] == from_pad)
          return i;
      }
    } else {
      return translation_table[from_pad];
    }
  }

  // no translation
  return from_pad;
}
