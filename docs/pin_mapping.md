# Pin Mapping - ESP32 DOIT DevKit V1

Hardware configuration for ESP32 with OLED, INMP441, RC522, and MAX98357A modules.

---

## Power & Ground

| Module    | Voltage  |
| --------- | -------- |
| OLED      | 3.3V     |
| INMP441   | 3.3V     |
| RC522     | 3.3V     |
| MAX98357A | 5V (VIN) |

**Important:**

* All modules must share common GND with ESP32
* Use star topology for GND connections to reduce noise

**Wire Color Convention (recommended):**

| Signal | Color         |
| ------ | ------------- |
| 5V     | Red           |
| 3.3V   | Orange        |
| GND    | Black / Brown |

---

## Module Connections

### 1. OLED SSD1306 (I2C)

| OLED Pin  | ESP32 Pin    | Wire Color (rcm) | Notes         |
| --------- | ------------ | ---------------- | ------------- |
| VDD / VCC | 3V3          | Orange           | Do not use 5V |
| GND       | GND          | Black            |               |
| SCK / SCL | D22 (GPIO22) | White            | I2C Clock     |
| SDA       | D21 (GPIO21) | Blue             | I2C Data      |

---

### 2. INMP441 Microphone (I2S RX)

| INMP441 Pin | ESP32 Pin    | Wire Color (rcm) | Notes                         |
| ----------- | ------------ | ---------------- | ----------------------------- |
| VDD         | 3V3          | Orange           |                               |
| GND         | GND          | Black            |                               |
| SCK (BCLK)  | D26 (GPIO26) | Purple           | I2S Clock (Shared with AMP)   |
| WS (LRCLK)  | D27 (GPIO27) | Yellow           | Word Select (Shared with AMP) |
| SD (DATA)   | D32 (GPIO32) | Blue             | Data from mic                 |
| L/R         | GND          | Brown            | Selects RIGHT channel         |

**Note:** Use RIGHT channel in code. Keep I2S wires short and separate from SPI.

---

### 3. RC522 RFID (SPI)

| RC522 Pin | ESP32 Pin    | Wire Color (rcm) | Notes                |
| --------- | ------------ | ---------------- | -------------------- |
| 3.3V      | 3V3          | Orange           | **Do not use 5V**    |
| GND       | GND          | Black            |                      |
| RST       | D17 / GPIO17 | Brown            | Labeled TX2 on board |
| SDA / SS  | D16 / GPIO16 | White            | Labeled RX2 on board |
| SCK       | D18 (GPIO18) | Yellow           |                      |
| MISO      | D19 (GPIO19) | Purple           |                      |
| MOSI      | D23 (GPIO23) | Green            |                      |
| IRQ       | NC           | -                | Not connected        |

**Noise reduction:** Add 0.1µF + 10µF capacitors between 3.3V and GND at RC522.

---

### 4. MAX98357A Amplifier (I2S TX)

| MAX98357A Pin | ESP32 Pin    | Wire Color (rcm) | Notes                                  |
| ------------- | ------------ | ---------------- | -------------------------------------- |
| VIN           | VIN (5V)     | Red              | Amp power                              |
| GND           | GND          | Black            |                                        |
| DIN           | D25 (GPIO25) | Gray             | I2S Data                               |
| BCLK          | D26 (GPIO26) | Purple           | I2S Clock                              |
| LRC / LRCLK   | D27 (GPIO27) | Yellow           | Word Select                            |
| SD            | D13 (GPIO13) | Brown            | Enable/shutdown (GPIO controlled)      |
| GAIN          | NC           | -                | Default gain; connect to GND to reduce |

**Speaker:**

* Connect to SPK+ / SPK- (or OUT+ / OUT-) on module
* Do not connect speaker to GND

---

## Quick Reference

| Bus          | Pins                                                        |
| ------------ | ----------------------------------------------------------- |
| I2C          | SDA=21, SCL=22                                              |
| SPI (RC522)  | SS=GPIO16 (RX2), RST=GPIO17 (TX2), SCK=18, MISO=19, MOSI=23 |
| I2S MIC (RX) | BCLK=26, WS=27, SD=32, L/R=GND                              |
| I2S AMP (TX) | DIN=25, BCLK=26, LRC=27, SD=13                              |
