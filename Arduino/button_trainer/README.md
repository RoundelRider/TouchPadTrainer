# button_trainer

Button-based version of the touchpad trainer firmware. It uses the same serial
protocol as [touchpad_trainer](../touchpad_trainer), so the App works with
either board.

## Hardware

| XIAO ESP32-C3 pin | Connection                                  |
|-------------------|---------------------------------------------|
| D2 (GPIO4)        | PCF8574 `INT` (open drain, internal pull-up) |
| D3 (GPIO5)        | WS2812B LED array data in                   |
| D4 (GPIO6) SDA    | PCF8574 `SDA`                               |
| D5 (GPIO7) SCL    | PCF8574 `SCL`                               |

PCF8574 inputs (switches to GND, read active low):

| Pin   | Switch          |
|-------|-----------------|
| P0    | Center          |
| P1–P4 | Ring corners 1–4 |

Pressing the center switch or any corner switch counts as a touch of the pad.
The sketch logs which switches were pressed (`DEBUG: Pad n pressed, switches 0x..`).

## Configuration (`button_trainer.ino`)

- `board_addresses[]`: one PCF8574 address per pad, in pad order. The pad count
  comes from this list. All boards share the D2 interrupt line.
- `LEDS_PER_PAD`: LEDs per pad in the array.
- `translation_table`: optional logical-to-physical pad mapping.
- `BUTTON_ACTIVE_LOW` (`ButtonPad.h`): set to 0 if the switches pull the pins high.

## Libraries / board

- Board: **XIAO_ESP32C3** (esp32 by Espressif). Enable *USB CDC On Boot* for USB serial.
- **PCF8574 library** by Renzo Mischianti
- **Adafruit NeoPixel**

## CAPON / CAPOFF

The App sends `CAPON` before each test and `CAPOFF` afterward. In this firmware
`CAPON` starts and probes every PCF8574 and replies `CAPON OK`, or replies with
an `ERROR` line if a board doesn't respond. `CAPOFF` stops reading the boards.
