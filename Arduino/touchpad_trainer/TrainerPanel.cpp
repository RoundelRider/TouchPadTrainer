#include "TrainerPanel.h"

TrainerPanel::TrainerPanel(uint16_t pads, uint16_t leds_per_pad, Adafruit_NeoPixel *led_array)
  : pad_count(pads),
    leds_per_pad(leds_per_pad),
    led_array(led_array) {
  trainingActive = false;
  ClearLeds();
}

void TrainerPanel::ProcessCommand(const char* cmd) {
    /*
    New Program Requirements
    1) Check orientation on.  The #1 pad will be lit in a specified color so 
       that the user can verify pad orientation and pad number (there may be 
       up to four pads) in the main program.
    2) Check orientation off.  Turns off all leds.
    3) Test start pattern.  The pad may display a pattern in green lights to 
       indicate that the test is about to start.  This may be setting some of 
       the LED’s on each pad to green and blinking three times.
    4) Test end pattern.  Like the start pattern, the arduino controller will 
       set some number of leds to red and blink to indicate the test is complete.
    5) Single touch.  Set the leds on the the specified pad number to the 
       indicated color (may be white, green or red), and measure the time until 
       the pad is touched from the time the leds are enabled if the command 
       includes an “expect touch” indicator.  The pad will time out according 
       to the included timeout parameter.
    6) Dual touch.  Two adjacent pads are specified with the indicated color.  
       Like the single touch command, this command will specify an “expect touch” 
       indicator, and a time out parameter. Both pads must be touched to make a 
       successful “expect touch” result.
  */
  Serial.print("Processing command: "); Serial.println(cmd);
  if (strncmp(cmd, CMD_CHECK_ORIENTATION, strlen(CMD_CHECK_ORIENTATION)) == 0) {
    bool enable = false;
    char enable_str[10];
    if (sscanf(cmd + strlen(CMD_CHECK_ORIENTATION) + 1, "%9s", enable_str)) {
      enable = (strcmp(enable_str, "ON") == 0);
      CheckOrientation(enable);
    }
    else {
      Serial.println("Error: Invalid check orientation command parameters, expecting: <ON/OFF>");
    }
  }
  else if(strncmp(cmd, CMD_PATTERN, strlen(CMD_PATTERN)) == 0) {
    char pattern_str[10];
    if (sscanf(cmd + strlen(CMD_PATTERN) + 1, "%9s", pattern_str)) {
      if (strcmp(pattern_str, "START") == 0) {
        LedPatternStart();
      }
      else if(strcmp(pattern_str, "END") == 0) {
        LedPatternEnd();
      }
      else {
        Serial.println("ERROR: Invalid pattern command parameter.  Expected <START/END>");
      }
    }
    else {
      Serial.println("ERROR: Invalid pattern command parameter.  Expected <START/END>");
    }
  }
  else if (strncmp(cmd, CMD_TOUCH_SINGLE, strlen(CMD_TOUCH_SINGLE)) == 0) {
    // <pad number> <color> <expect touch> <timeout>     
    int padNumber = -1;
    char colorStr[13];
    char expectTouchStr[7];
    uint32_t timeout = 0;
    if (sscanf(cmd + strlen(CMD_TOUCH_SINGLE) + 1, "%d %12s %6s %u", &padNumber, colorStr, expectTouchStr, &timeout)) {
      uint32_t color = GetLedColorFromString(colorStr);
      bool expectTouch = true;
      if (strcmp(expectTouchStr, "FALSE") == 0)
        bool expectTouch = false;

      StartSingleTouch(padNumber, color, expectTouch, timeout);
    }
    else {
      Serial.print("ERROR: Invalid ");
      Serial.print(CMD_TOUCH_SINGLE);
      Serial.println(" command parameters. Expected: <pad number> <Color: WHITE|GREEN|RED> <ExpectTouch: TRUE|FALSE> <timeout ms>");
    }
  }
  else if (strncmp(cmd, CMD_TOUCH_DOUBLE, strlen(CMD_TOUCH_DOUBLE)) == 0) {
    // <pad number 1> <pad number 2> <color> <expect touch> <timeout>
    int padNumber1 = -1;
    int padNumber2 = -1;
    char colorStr[13];
    char expectTouchStr[7];
    uint32_t timeout = 0;
    if (sscanf(cmd + strlen(CMD_TOUCH_SINGLE) + 1, "%d %d %12s %6s %u", &padNumber1, &padNumber2, colorStr, expectTouchStr, &timeout)) {
      uint32_t color = GetLedColorFromString(colorStr);
      bool expectTouch = true;
      if (strcmp(expectTouchStr, "FALSE") == 0)
        bool expectTouch = false;

      StartDoubleTouch(padNumber1, padNumber2, color, expectTouch, timeout);
    }
    else {
      Serial.print("ERROR: Invalid ");
      Serial.print(CMD_TOUCH_SINGLE);
      Serial.println(" command parameters. Expected: <pad number> <Color: WHITE|GREEN|RED> <ExpectTouch: TRUE|FALSE> <timeout ms>");
    }
  }
  else if(strncmp(cmd, CMD_CANCEL, strlen(CMD_CANCEL)) == 0) {

  }
}

void TrainerPanel::Tick() {
  uint32_t now = millis();

  // determine if the pad has expired
  if (now >= padEndMs) {
    // pad expired with no touch
    SendPadResult();
  }
}

void TrainerPanel::Touch(uint16_t touchedPadId, uint32_t touchedMs) {
  // If the touch occurred before the pad start, then disregard
  if (touchedMs < padStartMs)
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
  // if enable is true, then turn 1 led on on pad 1, and two on pad 2
  ClearLeds(false);
  if (enable) {
    // led 0 on pad 1
    SetLed(0, 0, LED_COLOR_WHITE, false, false);
    // led 0 and 1 on pad 2
    SetLed(1, 0, LED_COLOR_WHITE, false, false);
    SetLed(1, 0, LED_COLOR_WHITE, false, false);
  }
  led_array->show();

  Serial.print(CMD_CHECK_ORIENTATION);
  Serial.print(" is ");
  Serial.println(enable ? "ON": "OFF");
}

void TrainerPanel::LedPatternStart() {
  // Flas green leds 
  FlashLeds(3, LED_COLOR_GREEN);
}

void TrainerPanel::LedPatternEnd() {
  FlashLeds(3, LED_COLOR_RED);
}

void TrainerPanel::StartSingleTouch(int pad_number, uint32_t color, bool expect_touch, uint16_t timeout) {
  Serial.print("StartSingleTouch pad:");
  Serial.print(pad_number);
  Serial.print(" color: ");
  Serial.print(color, HEX);
  Serial.print(" expect touch: ");
  Serial.print(expect_touch);
  Serial.print(" timeout ms: ");
  Serial.println(timeout);

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

void TrainerPanel::StartDoubleTouch(int pad_number_1, int pad_number_2, uint32_t color, bool expect_touch, uint16_t timeout) {
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

void TrainerPanel::SetPadLeds(uint16_t pad, uint32_t color, bool clear, bool show)
{
  // Set all pad LEDs to the specified color
  uint16_t padLedIndex = pad * leds_per_pad;
  if (clear) led_array->clear();
  for (int i = 0; i < leds_per_pad; i++) {
    led_array->setPixelColor(padLedIndex + i, padLedColor);
  }
  if (show) led_array->show();
}

void TrainerPanel::SendPadResult() {
  // Send the following response:
  // SINGLE_PAD_RESULT <pad id> <touched> <response time>
  // DOUBLE_PAD_RESULT <pad 1 id> <pad 2 id> <touched> <response time>

  trainingActive = false;
  ClearLeds();

  // result for a single pad
  if (activePadCount == 1) {
    // determine if the pad was touched, and if so calcualte the reaction time
    bool pad_touched = false;
    uint32_t reaction_time = 0;
    if (padTouched[0]) {
      pad_touched = true;
      reaction_time = padTouchMs[0] - padStartMs;
    }

    Serial.print("SINGLE_PAD_RESULT ");
    Serial.print(padIds[0]);
    Serial.print(padTouched[0] ? " TRUE " : " FALSE ");
    Serial.println(reaction_time);
  }
  // result for a double pad
  else {
    // determine if both pads were touched
    bool pad_touched = padTouched[0] && padTouched[1];
    uint32_t reaction_time = max(padTouchMs[0], padTouchMs[1]) - padStartMs;
    if (!pad_touched)
      reaction_time = padEndMs - padStartMs;

    Serial.print("DOUBLE_PAD_RESULT ");
    Serial.print(padIds[0]);
    Serial.print(" ");
    Serial.print(padIds[1]);
    Serial.print(padTouched[0] ? " TRUE " : " FALSE ");
    Serial.println(reaction_time);
  }
}

uint32_t TrainerPanel::GetLedColorFromString(char *color_string) {
  uint32_t color = LED_COLOR_OFF;   // default to off
  if (strcmp(color_string, LED_COLOR_NAME_RED) == 0)
    color = LED_COLOR_RED;
  else if (strcmp(color_string, LED_COLOR_NAME_GREEN) == 0)
    color = LED_COLOR_GREEN;
  else if (strcmp(color_string, LED_COLOR_NAME_WHITE) == 0)
    color = LED_COLOR_WHITE;
  return color;
}