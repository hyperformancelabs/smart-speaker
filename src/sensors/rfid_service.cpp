#include "sensors/rfid_service.h"

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

void rfidPoll(String &lastUid, int &pendingCardEvent) {
    if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
        lastUid = "";
        for (byte i = 0; i < rfid.uid.size; i++) {
            if (rfid.uid.uidByte[i] < 0x10) lastUid += "0";
            lastUid += String(rfid.uid.uidByte[i], HEX);
            if (i != rfid.uid.size - 1) lastUid += ":";
        }
        lastUid.toUpperCase();
        pendingCardEvent = 1;

        rfid.PICC_HaltA();
        rfid.PCD_StopCrypto1();
    }
}
