#pragma once

#include <Arduino.h>
#include "driver/i2s.h"

#ifndef I2S_PIN_NO_CHANGE
#define I2S_PIN_NO_CHANGE (-1)
#endif

// OLED (I2C)
constexpr uint8_t PIN_OLED_SDA = 21;
constexpr uint8_t PIN_OLED_SCL = 22;

// RFID RC522 (SPI)
constexpr uint8_t PIN_RFID_SS = 16;
constexpr uint8_t PIN_RFID_RST = 17;

// INMP441 Microphone (I2S RX)
constexpr uint8_t PIN_MIC_BCLK = 26;
constexpr uint8_t PIN_MIC_WS = 27;
constexpr uint8_t PIN_MIC_SD = 32;

// MAX98357A Amplifier (I2S TX)
constexpr uint8_t PIN_SPK_DIN = 25;
constexpr uint8_t PIN_SPK_BCLK = PIN_MIC_BCLK;
constexpr uint8_t PIN_SPK_LRC = PIN_MIC_WS;
constexpr uint8_t PIN_AMP_SD = 13;

// Shared I2S port for microphone capture
constexpr i2s_port_t I2S_PORT = I2S_NUM_0;

constexpr int SCREEN_WIDTH = 128;
constexpr int SCREEN_HEIGHT = 64;

constexpr int MIC_SAMPLE_RATE = 16000;
constexpr int MIC_DMA_LEN = 512;
constexpr int MIC_DMA_CNT = 8;
constexpr int FRAME_SAMPLES = 320;

constexpr int SPK_SAMPLE_RATE = 16000;

constexpr unsigned long SERIAL_BAUD_RATE = 115200;
constexpr int SERIAL_RAW_LINES = 32;

constexpr uint16_t WS_PORT = 81;
constexpr unsigned long WIFI_TIMEOUT_MS = 15000;
constexpr unsigned long WIFI_RETRY_MS = 5000;
