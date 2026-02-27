# Pin Mapping - ESP32 DOIT DevKit V1

Hardware configuration for ESP32 with OLED, INMP441, RC522, and MAX98357A modules.

---

## Power & Ground

| Module | Voltage |
|--------|---------|
| OLED | 3.3V |
| INMP441 | 3.3V |
| RC522 | 3.3V |
| MAX98357A | 5V (VIN) |

**Important:**
- All modules must share common GND with ESP32
- Use star topology for GND connections to reduce noise

---

## Module Connections

### 1. OLED SSD1306 (I2C)

| OLED Pin | ESP32 Pin | Notes |
|----------|-----------|-------|
| VDD / VCC | 3V3 | Do not use 5V |
| GND | GND | |
| SCK / SCL | D22 (GPIO22) | I2C Clock |
| SDA | D21 (GPIO21) | I2C Data |

---

### 2. INMP441 Microphone (I2S RX)

| INMP441 Pin | ESP32 Pin | Notes |
|-------------|-----------|-------|
| VDD | 3V3 | |
| GND | GND | |
| SCK (BCLK) | D14 (GPIO14) | I2S Clock |
| WS (LRCLK) | D33 (GPIO33) | Word Select |
| SD (DATA) | D32 (GPIO32) | Data from mic |
| L/R | GND | Selects RIGHT channel |

**Note:** Use RIGHT channel in code. Keep I2S wires short and separate from SPI.

---

### 3. RC522 RFID (SPI)

| RC522 Pin | ESP32 Pin | Notes |
|-----------|-----------|-------|
| 3.3V | 3V3 | **Do not use 5V** |
| GND | GND | |
| RST | D4 (GPIO4) | |
| SDA / SS | D5 (GPIO5) | Sensitive during boot |
| SCK | D18 (GPIO18) | |
| MISO | D19 (GPIO19) | |
| MOSI | D23 (GPIO23) | |
| IRQ | NC | Not connected |

**Noise reduction:** Add 0.1µF + 10µF capacitors between 3.3V and GND at RC522.

---

### 4. MAX98357A Amplifier (I2S TX)

| MAX98357A Pin | ESP32 Pin | Notes |
|---------------|-----------|-------|
| VIN | VIN (5V) | Amp power |
| GND | GND | |
| DIN | D25 (GPIO25) | I2S Data |
| BCLK | D26 (GPIO26) | I2S Clock |
| LRC / LRCLK | D27 (GPIO27) | Word Select |
| SD | D13 (GPIO13) | Enable/shutdown (GPIO controlled) |
| GAIN | NC | Default gain; connect to GND to reduce |

**Speaker:**
- Connect to SPK+ / SPK- (or OUT+ / OUT-) on module
- Do not connect speaker to GND

---

## Quick Reference

| Bus | Pins |
|-----|------|
| I2C | SDA=21, SCL=22 |
| SPI (RC522) | SS=5, RST=4, SCK=18, MISO=19, MOSI=23 |
| I2S MIC (RX) | BCLK=14, WS=33, SD=32, L/R=GND |
| I2S AMP (TX) | DIN=25, BCLK=26, LRC=27, SD=13 |
