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
#define CMD_CHECK_ORIENTATION "ORIENTATION" // <ON/OFF>
#define CMD_PATTERN "PATTERN"                     // <START/END>
#define CMD_TOUCH_SINGLE "SINGLE"           // <pad number> <color> <expect touch> <timeout> 
#define CMD_TOUCH_DOUBLE "DOUBLE"           // <pad number 1> <pad number 2> <color> <expect touch> <timeout> 
#define CMD_CANCEL "CANCEL"

#define MAX_CONCURRENT_PADS 2

class TrainerPanel {
  public:
    TrainerPanel(uint16_t pads, uint16_t leds_per_pad, Adafruit_NeoPixel *led_array);

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
    void SetPadLeds(uint16_t pad, uint32_t color, bool clear=true, bool show=true);
    uint32_t GetLedColorFromString(char *color_string);

    void SendPadResult();

    // physical configuration
    uint16_t pad_count;
    uint16_t leds_per_pad;
    Adafruit_NeoPixel *led_array;

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