#include "sensors/rfid_service.h"

#include <cstdio>
#include <SPI.h>
#include <MFRC522.h>

#include "app_config.h"

namespace {
MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);
}

void rfidInit() {
    SPI.begin(18, 19, 23, PIN_RFID_SS);
    SPI.setFrequency(1000000);
    rfid.PCD_Init();
}

bool rfidPoll(char uidOut[], size_t uidOutSize) {
    if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
        return false;
    }

    if (uidOutSize > 0) {
        uidOut[0] = '\0';
    }

    size_t writePos = 0;

    for (byte i = 0; i < rfid.uid.size && writePos < uidOutSize; ++i) {
        int written = snprintf(uidOut + writePos, uidOutSize - writePos,
                               (i == 0) ? "%02X" : ":%02X", rfid.uid.uidByte[i]);
        if (written < 0) {
            break;
        }
        writePos += static_cast<size_t>(written);
        if (writePos >= uidOutSize) {
            uidOut[uidOutSize - 1] = '\0';
            break;
        }
    }

    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    return true;
}
