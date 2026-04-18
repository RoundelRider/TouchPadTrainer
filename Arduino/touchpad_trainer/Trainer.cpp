#include "Trainer.h"

Trainer::Trainer(uint16_t pads, uint16_t leds_per_pad, Adafruit_NeoPixel *led_array)
  : pad_count(pads),
    leds_per_pad(leds_per_pad),
    led_array(led_array) {
  trainingActive = false;
  randomSeed(analogRead(A0));
}

void Trainer::ProcessCommand(const char* cmd) {
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
  /*
  Serial.print("Processing command: "); Serial.println(cmd);
  if (strncmp(cmd, CMD_CHECK_ORIENTATION, strlen(CMD_CHECK_ORIENTATION)) == 0) {
    enable = false;
    enable_str[10];
    if (sscanf(cmd + strlen(CMD_CHECK_ORIENTATION) + 1, "%9s", enable_str)) {
      enable = (strcmp(enable_str, "ON") == 0);
      CheckOrientation(enable);
    }
    else {
      Serial.println("Error: Invalid check orientation command parameters, expecting: <ON/OFF>");
    }
  }
  else if(strncmp(cmd, CMD_PATTERN, strlen(CMD_PATTERN)) == 0) {
    pattern_str[10];
    if (sscanf(cmd + strlen(CMD_PATTERN) + 1, "%9s", enable_str)) {
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

  }
  */

  /*
  * Serial Protocol (115200 baud):
  *   PC -> Arduino:
  *     START <duration_sec> <speed_ms> <type>
  *       type: SIMPLE | SELECTIVE | SOLID
  *     STOP
  *     STATUS
  */
  Serial.print("Processing command: "); Serial.println(cmd);
  if (strncmp(cmd, "START", 5) == 0) {
    if (trainingActive) {
      return;
    }

    uint32_t duration;
    uint32_t step_duration;
    uint16_t mode;
    char     typeStr[16];
    if (sscanf(cmd + 6, "%lu %lu %15s", &duration, &step_duration, typeStr) != 3) {
      Serial.println(F("ERROR Usage: START <dur_sec> <speed_ms> <SIMPLE|SELECTIVE>"));
      return;
    }
    
    // convert duration from seconds to milliseconds
    duration *= 1000UL;
    mode = TRAINING_MODE_SIMPLE;
    if (strcmp(typeStr, "SOLID") == 0)
      mode = TRAINING_MODE_SOLID;
    else if (strcmp(typeStr, "SELECTIVE") == 0)
      mode = TRAINING_MODE_SELECTIVE;

    StartTraining(duration, step_duration, mode);
    return;    
  }

  if (strcmp(cmd, "STOP") == 0) {
    if (trainingActive) StopTraining();
    return;
  } 

  if (strcmp(cmd, "STATUS") == 0) {
    Serial.print("Training Active: ");
    Serial.print(trainingActive ? "YES": "NO");
    Serial.print(" Current pad: ");
    Serial.print(padId);
    Serial.print(" Hits: ");
    Serial.print(statHits);
    Serial.print(" Misses: ");
    Serial.print(statMisses);
    Serial.print(" NoTouch: ");
    Serial.print(statNoTouch);
    Serial.println("");
    return;
  }
 }

void Trainer::Tick() {
  uint32_t now = millis();
  bool testExpired = (now > trainingEndMs);

  // determine if the pad has expired
  if (now >= padEndMs) {
    // pad expired with no touch
    statNoTouch++;
    if (!testExpired) {
      // pause a random amount between 200ms and 1 second then start a new pad
      uint32_t delayMs = random(PAD_DELAY_MIN, PAD_DELAY_MAX);
      if ((now + delayMs) < trainingEndMs) {
        // delay then start a new
        Serial.print("Pad "); Serial.print(padId); Serial.println(" expired - selecting new pad"); 
        SelectPad(delayMs);
        return;
      }
      else {
        // test will expire before the end of the delay to the next pad, so stop here
        testExpired = true;
      }
    }
  }
  
  // Check for the pad tick expiration
  if (now >= padNextTickMs) {
    // If the padLedTickIndex is 0 then the pad should have expired above
    if (padLedTickIndex > 0) {
      if (trainingMode == TRAINING_MODE_SIMPLE) {
        // turn off pad led at padLedTickIndex
        SetLed(padId, padLedTickIndex, LED_COLOR_OFF, false, true);

        // update padLedTickIndex and padNextTickMs
        padLedTickIndex--;
        padNextTickMs += (trainingStepMs / leds_per_pad);
      }

      return;
    }
    else {
      padNextTickMs = 0;
    }
  }

  // If the test has expired and the pad is complete, then stop
  if (testExpired && padNextTickMs == 0) {
    StopTraining();
  }
}

void Trainer::Touch(uint16_t touchedPadId, uint32_t touchedMs) {
  // If the touch occurred before the pad start, then disregard
  if (touchedMs < padStartMs)
    return;

  // pad touched - check if the pad id is correct and record the response time
  uint32_t reactionTimeMs = touchedMs - padStartMs;
  if (touchedPadId == padId) {
    statHits++;
    statHitReactionMs += reactionTimeMs;
    Serial.print("Pad "); Serial.print(padId); Serial.print(" hit recorded, reaction time: "); Serial.println(reactionTimeMs); 
  }
  else {
    statMisses++;
    statMissReactionMs += reactionTimeMs;
    Serial.print("Pad "); Serial.print(padId); Serial.print(" miss recorded, reaction time: "); Serial.println(reactionTimeMs); 
  }

  // Choose a new pad if the delay won't be past the end of training
  // pause a random amount between 200ms and 1 second then start a new pad
  uint32_t delayMs = random(PAD_DELAY_MIN, PAD_DELAY_MAX);
  if ((millis() + delayMs) < trainingEndMs) {
    // delay then start a new
    SelectPad(delayMs);
  }
  else {
    // Training completed
    StopTraining();
  }
}

void Trainer::ClearLeds(bool show) {
  led_array->clear();
  if (show) led_array->show();
}

void Trainer::CheckOrientation(bool enable) {
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
}

void Trainer::LedPatternStart() {
  // Flas green leds 
  FlashLeds(3, LED_COLOR_GREEN);
}

void Trainer::LedPatternEnd() {
  FlashLeds(3, LED_COLOR_RED);
}

void Trainer::StartSingleTouch(int pad_number, uint32_t color, bool expect_touch, uint16_t timeout) {

}

void Trainer::StartDoubleTouch(int pad_number_1, int pad_number_2, uint32_t color, bool expect_touch, uint16_t timeout) {

}

void Trainer::StartTraining(uint32_t duration, uint32_t step_duration, uint16_t mode) {
  // training information
  trainingActive = true;
  trainingStartMs = millis();
  trainingEndMs = trainingStartMs + duration;
  trainingStepMs = step_duration;
  trainingMode = mode;

  // pad information during training
  padCounter = 0;
  padId = pad_count;
  padTouchId = pad_count;
  padTouchMs = 0;
  padStartMs = 0;
  padEndMs = 0;
  padNextTickMs = 0;

  // training stats for current session
  statHits = 0;
  statMisses = 0;
  statNoTouch = 0;
  statHitReactionMs = 0;
  statMissReactionMs = 0;

  // Flash All LEDs Green to start
  FlashLeds(3, LED_COLOR_GREEN);

  // Select random pad if we have any
  if (pad_count > 0)
    SelectPad();
}

void Trainer::StopTraining() {
  // clear training information
  trainingActive = false;
  trainingStartMs = 0;
  trainingEndMs = 0;
  trainingStepMs = 0;

  // Flash leds for end of test and return results via serial
  ClearLeds();
  delay(1000);
  FlashLeds(3, LED_COLOR_RED);

  // Print results to serial
  Serial.print("Tries: ");
  Serial.print(padCounter);
  Serial.print(", Hits: ");
  Serial.print(statHits);
  Serial.print(", Misses: ");
  Serial.print(statMisses);
  Serial.print(", NoTouch: ");
  Serial.print(statNoTouch);
  Serial.print(", HitReactionTime: ");
  Serial.print((statHits > 0) ? statHitReactionMs / statHits : 0);
  Serial.print(", MissReactionTime: ");
  Serial.println((statMisses > 0) ? statMissReactionMs / statMisses: 0);
}

void Trainer::SelectPad(uint32_t delayMs) {
  // Pause a random time up to 1 second between pads
  //Serial.println("Clear LEDs");
  ClearLeds();
  //Serial.print("Delaying Ms:"); Serial.println(delayMs);
  delay(delayMs);
  
  // Pick a new pad - may be the same or a different pad
  int next= random(0, pad_count);
  /*
  do {
    next = random(0, pad_count);
    if (pad_count == 1)
      break;
  } while (next == padId);
  */

  // initialize current pad values
  padCounter++;
  padId = next;
  padTouchId = -1;
  padTouchMs = 0;
  padStartMs = millis();
  padEndMs = padStartMs + trainingStepMs;
  padNextTickMs = padStartMs + (trainingStepMs / leds_per_pad);
  padLedTickIndex = leds_per_pad - 1;

  if (trainingMode == TRAINING_MODE_SIMPLE) {
    padLedColor  = LED_COLOR_WHITE;
    padExpectTouch  = true;
  } else {
    // SELECTIVE: 50/50 green/red
    if (random(0, 2) == 0) {
      padLedColor = LED_COLOR_GREEN;
      padExpectTouch = true;
    } else {
      padLedColor = LED_COLOR_RED;
      padExpectTouch = false;
    }
  }

  SetPadLeds(padId, padLedColor);

  /*
  Serial.print("PAD ");
  Serial.print(padId);
  Serial.print(" Start of ");
  Serial.println(padCounter);
  */
}

void Trainer::FlashLeds(uint16_t count, uint32_t color) {
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

void Trainer::SetLed(uint16_t pad, uint16_t index, uint32_t color, bool clear, bool show) {
  uint16_t padLedIndex = pad * leds_per_pad;
  if (clear) led_array->clear();
  led_array->setPixelColor(padLedIndex + index, color);
  if (show) led_array->show();
}

void Trainer::SetPadLeds(uint16_t pad, uint32_t color)
{
  // Set all pad LEDs to the specified color
  uint16_t padLedIndex = pad * leds_per_pad;
  led_array->clear();
  for (int i = 0; i < leds_per_pad; i++) {
    led_array->setPixelColor(padLedIndex + i, padLedColor);
  }
  led_array->show();
}
