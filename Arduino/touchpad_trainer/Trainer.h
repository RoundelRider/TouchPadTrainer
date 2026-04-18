#include <Adafruit_NeoPixel.h>

#define LED_COLOR_WHITE 0xFFFFFF
#define LED_COLOR_RED   0xFF0000
#define LED_COLOR_GREEN 0x00FF00
#define LED_COLOR_OFF   0x000000

// LED color names
#define LED_COLOR_NAME_WHITE  "WHITE"
#define LED_COLOR_NAME_RED    "RED"
#define LED_COLOR_NAME_GREEN  "GREEN"

// Serial commands                                   params
#define CMD_CHECK_ORIENTATION "CHECK_ORIENTATION" // <ON/OFF>
#define CMD_PATTERN "START_PATTERN"               // <START/END>
#define CMD_TOUCH_SINGLE "TOUCH_SINGLE"           // <pad number> <color> <expect touch> <timeout> 
#define CMD_TOUCH_DOUBLE "TOUCH_DOUBLE"           // <pad number 1> <pad number 2> <color> <expect touch> <timeout> 

class Trainer {
  public:
    Trainer(uint16_t pads, uint16_t leds_per_pad, Adafruit_NeoPixel *led_array);

    void ProcessCommand(const char* cmd);

    void Tick();
    void Touch(uint16_t touchedPadId, uint32_t touchMs);
    
    bool isTrainingActive() { return trainingActive; }

    void ClearLeds(bool show=true);

  protected:
    // new commands handlers
    void CheckOrientation(bool enable);
    void LedPatternStart();
    void LedPatternEnd();
    void StartSingleTouch(int pad_number, uint32_t color, bool expect_touch, uint16_t timeout);
    void StartDoubleTouch(int pad_number_1, int pad_number_2, uint32_t color, bool expect_touch, uint16_t timeout);

    void FlashLeds(uint16_t count, uint32_t color);
    void SetLed(uint16_t pad, uint16_t index, uint32_t color, bool clear=true, bool show=true);
    void SetPadLeds(uint16_t pad, uint32_t color);

    // physical configuration
    uint16_t pad_count;
    uint16_t leds_per_pad;
    Adafruit_NeoPixel *led_array;

    // training information
    bool trainingActive;
    uint32_t trainingStartMs;
    uint32_t trainingEndMs;
    uint32_t trainingStepMs;
    uint16_t trainingMode;

    // pad information during training
    uint16_t padCounter;
    uint16_t padId;
    uint16_t padTouchId;
    uint32_t padTouchMs;
    uint32_t padStartMs;
    uint32_t padEndMs;
    uint32_t padNextTickMs;
    uint16_t padLedTickIndex;
    uint32_t padLedColor;
    bool padExpectTouch;

    // training stats for current session
    uint16_t statHits;
    uint16_t statMisses;
    uint16_t statNoTouch;
    uint32_t statHitReactionMs;
    uint32_t statMissReactionMs;
};