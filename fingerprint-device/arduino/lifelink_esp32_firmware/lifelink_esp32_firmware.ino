/*
  =============================================================================
  LifeLink 2.0 - ESP32 Official Firmware for GT-521F32 Fingerprint Scanner
  =============================================================================

  Hardware Wiring (ESP32 DevKit to GT-521F32):
    GT-521F32 TX   -> ESP32 GPIO 16 (RX2)
    GT-521F32 RX   -> ESP32 GPIO 17 (TX2)
    GT-521F32 GND  -> ESP32 GND
    GT-521F32 VIN  -> ESP32 VIN / 5V (USB 5V power rail)

  Baud Rates:
    USB Serial (to PC / Pi 5 / Serial Monitor): 115200 baud
    Sensor UART2 (to GT-521F32):                  9600 baud (sensor factory default)

  Dual Operating Mode:
    1. LifeLink Production Host Link:
       Responds to binary LLFP framed commands from LifeLink Kiosk (Pi 5 or PC).
       Supports: HELLO, LED, 3-Pass Enrollment, Template Extraction, 1:1 Verify.
    2. Arduino Serial Monitor Diagnostic Mode:
       Type single-letter commands in the Serial Monitor (115200 baud, Newline):
         's' -> Scan single finger
         'e' -> Guided 3-pass enrollment test
         'v' -> 1:1 verification test
         'l' -> Toggle sensor LED
         'r' -> Reconnect to sensor
         'h' -> Display diagnostic menu
  =============================================================================
*/

#include <Arduino.h>

// UART Configuration
constexpr int SENSOR_RX = 16;
constexpr int SENSOR_TX = 17;
constexpr uint32_t HOST_BAUD = 115200;
constexpr uint32_t SENSOR_BAUD = 9600;

HardwareSerial sensorSerial(2);

// LLFP Protocol Constants
constexpr uint8_t MAGIC[4] = {'L', 'L', 'F', 'P'};
constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint8_t KIND_REQUEST  = 0x01;
constexpr uint8_t KIND_RESPONSE = 0x02;

constexpr uint16_t CMD_HELLO         = 0x0001;
constexpr uint16_t CMD_STATUS        = 0x0002;
constexpr uint16_t CMD_LED           = 0x0003;
constexpr uint16_t CMD_ENROLL_START  = 0x0010;
constexpr uint16_t CMD_ENROLL_PASS   = 0x0011;
constexpr uint16_t CMD_GET_TEMPLATE  = 0x0012;
constexpr uint16_t CMD_LOAD_TEMPLATE = 0x0013;
constexpr uint16_t CMD_VERIFY_1_1    = 0x0014;
constexpr uint16_t CMD_DELETE_SLOT   = 0x0015;
constexpr uint16_t CMD_CAPTURE_SINGLE = 0x0016;
constexpr uint16_t CMD_CANCEL        = 0x001F;

constexpr uint16_t STATUS_OK           = 0x0000;
constexpr uint16_t STATUS_ERROR        = 0x0001;
constexpr uint16_t STATUS_TIMEOUT      = 0x0002;
constexpr uint16_t STATUS_BAD_CHECKSUM = 0x0003;
constexpr uint16_t STATUS_BUSY         = 0x0004;
constexpr uint16_t STATUS_BAD_FINGER   = 0x0005;

// GT-521F32 Sensor Opcodes
constexpr uint16_t GT_CMD_OPEN            = 0x01;
constexpr uint16_t GT_CMD_CLOSE           = 0x02;
constexpr uint16_t GT_CMD_CMOS_LED        = 0x12;
constexpr uint16_t GT_CMD_ENROLL_START    = 0x22;
constexpr uint16_t GT_CMD_ENROLL1         = 0x23;
constexpr uint16_t GT_CMD_ENROLL2         = 0x24;
constexpr uint16_t GT_CMD_ENROLL3         = 0x25;
constexpr uint16_t GT_CMD_IS_PRESS_FINGER = 0x26;
constexpr uint16_t GT_CMD_DELETE_ID       = 0x40;
constexpr uint16_t GT_CMD_DELETE_ALL      = 0x41;
constexpr uint16_t GT_CMD_VERIFY          = 0x50;
constexpr uint16_t GT_CMD_CAPTURE_FINGER  = 0x60;
constexpr uint16_t GT_CMD_GET_TEMPLATE    = 0x70;
constexpr uint16_t GT_CMD_SET_TEMPLATE    = 0x71;

constexpr uint16_t GT_ACK  = 0x30;
constexpr uint16_t GT_NACK = 0x31;
constexpr size_t TEMPLATE_SIZE = 498;
constexpr uint16_t SCRATCH_SLOT = 199;
uint16_t lastEnrolledSlot = SCRATCH_SLOT;

bool sensorReady = false;
bool ledState = false;

// ---------------------------------------------------------------------------
// CRC32 Checksum (IEEE 802.3 matching Python zlib.crc32)
// ---------------------------------------------------------------------------
uint32_t calculateCRC32(const uint8_t *data, size_t length) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < length; i++) {
    crc ^= data[i];
    for (int j = 0; j < 8; j++) {
      if (crc & 1)
        crc = (crc >> 1) ^ 0xEDB88320;
      else
        crc = crc >> 1;
    }
  }
  return ~crc;
}

// ---------------------------------------------------------------------------
// GT-521F32 Communication Helpers
// ---------------------------------------------------------------------------
bool sendSensorCommand(uint16_t cmd, uint32_t param, uint32_t &replyParam, uint32_t timeoutMs = 2000) {
  uint8_t pkt[12] = {
    0x55, 0xAA, 0x01, 0x00,
    uint8_t(param), uint8_t(param >> 8),
    uint8_t(param >> 16), uint8_t(param >> 24),
    uint8_t(cmd), uint8_t(cmd >> 8),
    0, 0
  };
  uint16_t chk = 0;
  for (int i = 0; i < 10; ++i) chk += pkt[i];
  pkt[10] = uint8_t(chk);
  pkt[11] = uint8_t(chk >> 8);

  while (sensorSerial.available()) sensorSerial.read();

  sensorSerial.write(pkt, 12);
  sensorSerial.flush();

  uint8_t resp[12];
  size_t rec = 0;
  uint32_t start = millis();
  while (rec < 12 && (millis() - start < timeoutMs)) {
    if (sensorSerial.available()) {
      resp[rec++] = uint8_t(sensorSerial.read());
    } else {
      delay(1);
    }
  }

  if (rec != 12) return false;
  if (resp[0] != 0x55 || resp[1] != 0xAA || resp[2] != 0x01 || resp[3] != 0x00) return false;

  uint16_t sum = 0;
  for (int i = 0; i < 10; ++i) sum += resp[i];
  uint16_t respChk = uint16_t(resp[10]) | (uint16_t(resp[11]) << 8);
  if (sum != respChk) return false;

  replyParam = uint32_t(resp[4]) | (uint32_t(resp[5]) << 8) |
               (uint32_t(resp[6]) << 16) | (uint32_t(resp[7]) << 24);
  uint16_t status = uint16_t(resp[8]) | (uint16_t(resp[9]) << 8);
  return (status == GT_ACK);
}

bool sensorSetLed(bool on) {
  uint32_t rep = 0;
  bool ok = sendSensorCommand(GT_CMD_CMOS_LED, on ? 1 : 0, rep, 1000);
  if (ok) ledState = on;
  return ok;
}

bool sensorIsPressFinger() {
  uint32_t rep = 0;
  bool ok = sendSensorCommand(GT_CMD_IS_PRESS_FINGER, 0, rep, 500);
  return (ok && rep == 0);
}

bool sensorCaptureFinger(bool highQuality = true, uint32_t timeoutMs = 7000) {
  uint32_t rep = 0;
  return sendSensorCommand(GT_CMD_CAPTURE_FINGER, highQuality ? 1 : 0, rep, timeoutMs);
}

bool sensorOpen() {
  uint32_t rep = 0;
  bool ok = sendSensorCommand(GT_CMD_OPEN, 0, rep, 2000);
  if (ok) {
    sensorReady = true;
    sensorSetLed(false);
  } else {
    sensorReady = false;
  }
  return ok;
}

bool sensorGetTemplate(uint16_t slotId, uint8_t *dest498) {
  uint32_t rep = 0;
  if (!sendSensorCommand(GT_CMD_GET_TEMPLATE, slotId, rep, 2000)) return false;

  // Sensor transmits 504-byte Data Packet:
  // 0x5A, 0xA5, 0x01, 0x00, 498 bytes data, 2 bytes checksum
  uint8_t dataHeader[4];
  size_t rec = 0;
  uint32_t start = millis();
  while (rec < 4 && (millis() - start < 3000)) {
    if (sensorSerial.available()) {
      dataHeader[rec++] = uint8_t(sensorSerial.read());
    } else {
      delay(1);
    }
  }
  if (rec != 4 || dataHeader[0] != 0x5A || dataHeader[1] != 0xA5) return false;

  rec = 0;
  start = millis();
  while (rec < 498 && (millis() - start < 3000)) {
    if (sensorSerial.available()) {
      dest498[rec++] = uint8_t(sensorSerial.read());
    } else {
      delay(1);
    }
  }
  if (rec != 498) return false;

  // Read trailing 2-byte checksum
  uint8_t chkBytes[2];
  rec = 0;
  start = millis();
  while (rec < 2 && (millis() - start < 1000)) {
    if (sensorSerial.available()) {
      chkBytes[rec++] = uint8_t(sensorSerial.read());
    } else {
      delay(1);
    }
  }
  return (rec == 2);
}

bool sensorSetTemplate(uint16_t slotId, const uint8_t *src498) {
  uint32_t rep = 0;
  if (!sendSensorCommand(GT_CMD_SET_TEMPLATE, slotId, rep, 2000)) return false;

  // Build and send 504-byte Data Packet
  uint8_t pkt[504];
  pkt[0] = 0x5A;
  pkt[1] = 0xA5;
  pkt[2] = 0x01;
  pkt[3] = 0x00;
  memcpy(&pkt[4], src498, 498);

  uint16_t sum = 0;
  for (int i = 0; i < 502; ++i) sum += pkt[i];
  pkt[502] = uint8_t(sum);
  pkt[503] = uint8_t(sum >> 8);

  sensorSerial.write(pkt, 504);
  sensorSerial.flush();

  // Wait for sensor ACK (12 bytes)
  uint8_t resp[12];
  size_t rec = 0;
  uint32_t start = millis();
  while (rec < 12 && (millis() - start < 2000)) {
    if (sensorSerial.available()) {
      resp[rec++] = uint8_t(sensorSerial.read());
    } else {
      delay(1);
    }
  }
  if (rec != 12) return false;
  uint16_t status = uint16_t(resp[8]) | (uint16_t(resp[9]) << 8);
  return (status == GT_ACK);
}

bool sensorDeleteSlot(uint16_t slotId) {
  uint32_t rep = 0;
  return sendSensorCommand(GT_CMD_DELETE_ID, slotId, rep, 1500);
}

bool sensorDeleteAll() {
  uint32_t rep = 0;
  return sendSensorCommand(GT_CMD_DELETE_ALL, 0, rep, 3000);
}

const char* getNackErrorString(uint32_t err) {
  switch (err) {
    case 0x1001: return "NACK_TIMEOUT";
    case 0x1002: return "NACK_INVALID_BAUDRATE";
    case 0x1003: return "NACK_INVALID_POS (Slot ID out of range for this sensor model)";
    case 0x1004: return "NACK_IS_NOT_USED (Slot ID not enrolled)";
    case 0x1005: return "NACK_IS_ALREADY_USED (Slot already contains a fingerprint)";
    case 0x1006: return "NACK_COMM_ERR";
    case 0x1007: return "NACK_VERIFY_FAILED";
    case 0x1008: return "NACK_IDENTIFY_FAILED";
    case 0x1009: return "NACK_DB_IS_FULL";
    case 0x100A: return "NACK_DB_IS_EMPTY";
    case 0x100B: return "NACK_TURN_ERR (Command sequence or finger position error)";
    case 0x100C: return "NACK_BAD_FINGER";
    case 0x100D: return "NACK_ENROLL_FAILED";
    case 0x100E: return "NACK_IS_NOT_SUPPORTED";
    case 0x100F: return "NACK_DEV_ERR";
    case 0x1010: return "NACK_CAPTURE_CANCELED";
    case 0x1011: return "NACK_INVALID_PARAM / ALREADY_USED";
    default: return "UNKNOWN_NACK";
  }
}

bool sensorVerify(uint16_t slotId) {
  uint32_t rep = 0;
  if (!sendSensorCommand(GT_CMD_VERIFY, slotId, rep, 3000)) return false;
  return (rep == 0);
}

// ---------------------------------------------------------------------------
// LLFP Binary Protocol Sender
// ---------------------------------------------------------------------------
void sendLLFPResponse(uint16_t cmd, const uint8_t *reqId, uint16_t status, const uint8_t *payload = nullptr, uint16_t payloadLen = 0) {
  uint8_t buffer[28 + 498 + 4];
  buffer[0] = 'L';
  buffer[1] = 'L';
  buffer[2] = 'F';
  buffer[3] = 'P';
  buffer[4] = PROTOCOL_VERSION;
  buffer[5] = KIND_RESPONSE;
  memcpy(&buffer[6], reqId, 16);
  buffer[22] = uint8_t(cmd & 0xFF);
  buffer[23] = uint8_t((cmd >> 8) & 0xFF);
  buffer[24] = uint8_t(status & 0xFF);
  buffer[25] = uint8_t((status >> 8) & 0xFF);
  buffer[26] = uint8_t(payloadLen & 0xFF);
  buffer[27] = uint8_t((payloadLen >> 8) & 0xFF);

  if (payloadLen > 0 && payload != nullptr) {
    memcpy(&buffer[28], payload, payloadLen);
  }

  size_t pktLenWithoutCRC = 28 + payloadLen;
  uint32_t crc = calculateCRC32(buffer, pktLenWithoutCRC);
  buffer[pktLenWithoutCRC]     = uint8_t(crc & 0xFF);
  buffer[pktLenWithoutCRC + 1] = uint8_t((crc >> 8) & 0xFF);
  buffer[pktLenWithoutCRC + 2] = uint8_t((crc >> 16) & 0xFF);
  buffer[pktLenWithoutCRC + 3] = uint8_t((crc >> 24) & 0xFF);

  Serial.write(buffer, pktLenWithoutCRC + 4);
  Serial.flush();
}

// ---------------------------------------------------------------------------
// LLFP Host Command Processor
// ---------------------------------------------------------------------------
void handleLLFPCommand(uint16_t cmd, const uint8_t *reqId, const uint8_t *payload, uint16_t payloadLen) {
  // 1. Handshake
  if (cmd == CMD_HELLO) {
    const char *ver = "LifeLink-ESP32-v2.0-wired";
    sendLLFPResponse(cmd, reqId, STATUS_OK, (const uint8_t*)ver, strlen(ver));
    return;
  }

  // 2. Peripheral Status
  if (cmd == CMD_STATUS) {
    uint8_t st[2] = { uint8_t(sensorReady ? 1 : 0), uint8_t(ledState ? 1 : 0) };
    sendLLFPResponse(cmd, reqId, STATUS_OK, st, 2);
    return;
  }

  // 3. LED Backlight
  if (cmd == CMD_LED) {
    bool on = (payloadLen > 0 && payload[0] != 0);
    bool ok = sensorSetLed(on);
    sendLLFPResponse(cmd, reqId, ok ? STATUS_OK : STATUS_ERROR);
    return;
  }

  // 4. Enroll Start (Pass 1)
  if (cmd == CMD_ENROLL_START) {
    sensorSetLed(true);
    sensorDeleteSlot(SCRATCH_SLOT);
    uint32_t rep = 0;
    if (!sendSensorCommand(GT_CMD_ENROLL_START, SCRATCH_SLOT, rep, 1000)) {
      if (rep == 0x1003) {
        sensorDeleteSlot(0);
        sendSensorCommand(GT_CMD_ENROLL_START, 0, rep, 1000);
      }
    }

    // Wait for finger press (up to 4000ms)
    uint32_t start = millis();
    bool pressed = false;
    while (millis() - start < 4000) {
      if (sensorIsPressFinger()) { pressed = true; break; }
      delay(40);
    }

    if (!pressed) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    if (!sensorCaptureFinger(true)) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    bool ok = sendSensorCommand(GT_CMD_ENROLL1, 0, rep, 2000);
    sensorSetLed(false);
    sendLLFPResponse(cmd, reqId, ok ? STATUS_OK : STATUS_ERROR);
    return;
  }

  // 5. Enroll Advance (Pass 2 or 3)
  if (cmd == CMD_ENROLL_PASS) {
    uint8_t passNum = (payloadLen > 0) ? payload[0] : 2;
    sensorSetLed(true);

    uint32_t start = millis();
    bool pressed = false;
    while (millis() - start < 4000) {
      if (sensorIsPressFinger()) { pressed = true; break; }
      delay(40);
    }

    if (!pressed) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    if (!sensorCaptureFinger(true)) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    uint32_t rep = 0;
    bool ok = false;
    if (passNum == 2) {
      ok = sendSensorCommand(GT_CMD_ENROLL2, 0, rep, 2000);
    } else {
      ok = sendSensorCommand(GT_CMD_ENROLL3, 0, rep, 2500);
    }
    sensorSetLed(false);

    sendLLFPResponse(cmd, reqId, ok ? STATUS_OK : STATUS_ERROR);
    return;
  }

  // 5b. Single-Impression Capture & Template Extraction
  if (cmd == CMD_CAPTURE_SINGLE) {
    sensorSetLed(true);
    sensorDeleteSlot(SCRATCH_SLOT);
    uint32_t rep = 0;
    if (!sendSensorCommand(GT_CMD_ENROLL_START, SCRATCH_SLOT, rep, 1000)) {
      if (rep == 0x1003) {
        sensorDeleteSlot(0);
        sendSensorCommand(GT_CMD_ENROLL_START, 0, rep, 1000);
      }
    }

    uint32_t start = millis();
    bool pressed = false;
    while (millis() - start < 8000) {
      if (sensorIsPressFinger()) { pressed = true; break; }
      delay(40);
    }

    if (!pressed) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    if (!sensorCaptureFinger(true)) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    bool ok = sendSensorCommand(GT_CMD_ENROLL1, 0, rep, 2000);
    if (ok) {
      delay(80);
      sensorCaptureFinger(true);
      sendSensorCommand(GT_CMD_ENROLL2, 0, rep, 1500);
      delay(80);
      sensorCaptureFinger(true);
      sendSensorCommand(GT_CMD_ENROLL3, 0, rep, 1500);
    }
    sensorSetLed(false);

    uint8_t tpl[TEMPLATE_SIZE];
    if (ok && sensorGetTemplate(SCRATCH_SLOT, tpl)) {
      sendLLFPResponse(cmd, reqId, STATUS_OK, tpl, TEMPLATE_SIZE);
    } else {
      sendLLFPResponse(cmd, reqId, STATUS_ERROR);
    }
    return;
  }

  // 6. Retrieve Enrolled Template (498 bytes)
  if (cmd == CMD_GET_TEMPLATE) {
    uint8_t tpl[TEMPLATE_SIZE];
    if (sensorGetTemplate(SCRATCH_SLOT, tpl)) {
      sendLLFPResponse(cmd, reqId, STATUS_OK, tpl, TEMPLATE_SIZE);
    } else {
      sendLLFPResponse(cmd, reqId, STATUS_ERROR);
    }
    return;
  }

  // 7. Load Template to Scratch Slot (498 bytes)
  if (cmd == CMD_LOAD_TEMPLATE) {
    if (payloadLen == TEMPLATE_SIZE && sensorSetTemplate(SCRATCH_SLOT, payload)) {
      sendLLFPResponse(cmd, reqId, STATUS_OK);
    } else {
      sendLLFPResponse(cmd, reqId, STATUS_ERROR);
    }
    return;
  }

  // 8. 1:1 Live Verification
  if (cmd == CMD_VERIFY_1_1) {
    sensorSetLed(true);

    uint32_t start = millis();
    bool pressed = false;
    while (millis() - start < 4000) {
      if (sensorIsPressFinger()) { pressed = true; break; }
      delay(40);
    }

    if (!pressed || !sensorCaptureFinger(false)) {
      sensorSetLed(false);
      sendLLFPResponse(cmd, reqId, STATUS_BAD_FINGER);
      return;
    }

    bool matched = sensorVerify(SCRATCH_SLOT);
    sensorSetLed(false);
    sendLLFPResponse(cmd, reqId, matched ? STATUS_OK : STATUS_ERROR);
    return;
  }

  // 9. Delete Template / Wipe Scratch Slot
  if (cmd == CMD_DELETE_SLOT) {
    uint16_t slot = SCRATCH_SLOT;
    if (payloadLen >= 2) {
      slot = payload[0] | (uint16_t(payload[1]) << 8);
    }
    bool ok = sensorDeleteSlot(slot);
    sendLLFPResponse(cmd, reqId, ok ? STATUS_OK : STATUS_ERROR);
    return;
  }

  // 10. Cancel Operation
  if (cmd == CMD_CANCEL) {
    sensorSetLed(false);
    sensorDeleteSlot(SCRATCH_SLOT);
    sendLLFPResponse(cmd, reqId, STATUS_OK);
    return;
  }

  sendLLFPResponse(cmd, reqId, STATUS_ERROR);
}

// ---------------------------------------------------------------------------
// Interactive Diagnostic Mode (For Arduino IDE Serial Monitor)
// ---------------------------------------------------------------------------
void printHelpMenu() {
  Serial.println(F("\n=== LifeLink 2.0 Fingerprint Diagnostics ==="));
  Serial.println(F("Available Serial Commands:"));
  Serial.println(F("  s - Scan finger (test single image capture)"));
  Serial.println(F("  e - Run 3-pass enrollment into scratch slot"));
  Serial.println(F("  v - Verify live finger against scratch slot"));
  Serial.println(F("  c - Clear / delete scratch slots (199 and 0)"));
  Serial.println(F("  d - Delete ALL enrolled fingerprints in sensor memory"));
  Serial.println(F("  l - Toggle sensor LED on/off"));
  Serial.println(F("  r - Reconnect to GT-521F32 sensor"));
  Serial.println(F("  h - Print this diagnostic menu"));
  Serial.println(F("---------------------------------------------"));
}

void interactiveScan() {
  if (!sensorReady) {
    Serial.println(F("ERROR: Sensor not connected. Send 'r' to retry."));
    return;
  }
  Serial.println(F("\n[TEST] Turning on sensor LED..."));
  sensorSetLed(true);

  Serial.println(F("Place your finger on the optical prism (15s timeout)..."));
  uint32_t start = millis();
  bool pressed = false;
  while (millis() - start < 15000) {
    if (sensorIsPressFinger()) { pressed = true; break; }
    delay(100);
  }

  if (!pressed) {
    Serial.println(F("FAIL: No finger detected."));
    sensorSetLed(false);
    return;
  }

  Serial.println(F("PASS: Finger detected! Capturing fingerprint..."));
  if (sensorCaptureFinger(true, 7000)) {
    Serial.println(F("PASS: Fingerprint image captured successfully in sensor RAM."));
    Serial.println(F("STATUS: SENSOR WORKING NORMALLY."));
  } else {
    Serial.println(F("FAIL: Fingerprint capture failed. Reposition finger."));
  }
  sensorSetLed(false);
}

void interactiveEnroll() {
  if (!sensorReady) {
    Serial.println(F("ERROR: Sensor not ready."));
    return;
  }

  uint16_t targetSlot = SCRATCH_SLOT;
  Serial.printf("\n=== Starting 3-Pass Enrollment on Scratch Slot %d ===\n", targetSlot);
  sensorSetLed(true);

  // GT-521F32 / GT-511C3 requirement:
  // If the slot is already enrolled, EnrollStart will be REJECTED with NACK_IS_ALREADY_USED.
  // We must delete the slot first to ensure it is clean.
  sensorDeleteSlot(targetSlot);

  uint32_t rep = 0;
  if (!sendSensorCommand(GT_CMD_ENROLL_START, targetSlot, rep, 1500)) {
    // If rejected with 0x1003 (NACK_INVALID_POS), this sensor has fewer slots (e.g. GT-511C1 has 20 slots: 0-19)
    if (rep == 0x1003) {
      Serial.printf("Notice: Slot %d is out of range for this sensor model (NACK_INVALID_POS).\n", targetSlot);
      Serial.println(F("Retrying enrollment on universal Slot 0..."));
      targetSlot = 0;
      sensorDeleteSlot(targetSlot);
      if (!sendSensorCommand(GT_CMD_ENROLL_START, targetSlot, rep, 1500)) {
        Serial.printf("FAIL: EnrollStart command rejected on Slot 0. NACK: 0x%04X (%s)\n", rep, getNackErrorString(rep));
        sensorSetLed(false);
        return;
      }
    } else {
      Serial.printf("FAIL: EnrollStart command rejected on Slot %d. NACK: 0x%04X (%s)\n", targetSlot, rep, getNackErrorString(rep));
      sensorSetLed(false);
      return;
    }
  }

  lastEnrolledSlot = targetSlot;
  Serial.printf("PASS: EnrollStart accepted for Slot %d!\n", targetSlot);

  for (int pass = 1; pass <= 3; pass++) {
    Serial.printf("\n[PASS %d of 3] Place your finger on the sensor...\n", pass);
    uint32_t start = millis();
    bool pressed = false;
    while (millis() - start < 10000) {
      if (sensorIsPressFinger()) { pressed = true; break; }
      delay(80);
    }
    if (!pressed) {
      Serial.println(F("FAIL: Timeout waiting for finger."));
      sensorSetLed(false);
      return;
    }

    if (!sensorCaptureFinger(true)) {
      Serial.println(F("FAIL: Capture failed."));
      sensorSetLed(false);
      return;
    }

    uint16_t cmd = (pass == 1) ? GT_CMD_ENROLL1 : ((pass == 2) ? GT_CMD_ENROLL2 : GT_CMD_ENROLL3);
    if (!sendSensorCommand(cmd, 0, rep, 2500)) {
      Serial.printf("FAIL: Enroll pass %d failed. NACK: 0x%04X (%s)\n", pass, rep, getNackErrorString(rep));
      sensorSetLed(false);
      return;
    }
    Serial.printf("PASS: Pass %d recorded successfully!\n", pass);

    if (pass < 3) {
      Serial.println(F("Please lift your finger..."));
      while (sensorIsPressFinger()) delay(80);
      delay(300);
    }
  }

  sensorSetLed(false);
  Serial.printf("\nSUCCESS: 3-pass fingerprint enrollment complete in slot %d!\n", targetSlot);
  Serial.println(F("You can now test verification by sending 'v'."));
}

void interactiveVerify() {
  if (!sensorReady) {
    Serial.println(F("ERROR: Sensor not ready."));
    return;
  }
  Serial.printf("\n[TEST] 1:1 Verification against Slot %d\n", lastEnrolledSlot);
  sensorSetLed(true);

  Serial.println(F("Place finger to verify (10s timeout)..."));
  uint32_t start = millis();
  bool pressed = false;
  while (millis() - start < 10000) {
    if (sensorIsPressFinger()) { pressed = true; break; }
    delay(80);
  }
  if (!pressed) {
    Serial.println(F("FAIL: No finger detected."));
    sensorSetLed(false);
    return;
  }

  if (!sensorCaptureFinger(false)) {
    Serial.println(F("FAIL: Capture failed."));
    sensorSetLed(false);
    return;
  }

  if (sensorVerify(lastEnrolledSlot)) {
    Serial.println(F(">>> MATCH VERIFIED! Fingerprint matches enrolled identity. <<<"));
  } else {
    Serial.printf(">>> MISMATCH: Fingerprint does NOT match slot %d. <<<\n", lastEnrolledSlot);
  }
  sensorSetLed(false);
}

// ---------------------------------------------------------------------------
// Arduino Setup & Main Loop
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(HOST_BAUD);
  sensorSerial.begin(SENSOR_BAUD, SERIAL_8N1, SENSOR_RX, SENSOR_TX);

  delay(1200);
  Serial.println(F("\n========================================="));
  Serial.println(F("LifeLink 2.0 - ESP32 Fingerprint Firmware"));
  Serial.println(F("USB: 115200 baud | Sensor UART2: 9600 baud"));
  Serial.println(F("GPIO: RX=16 (to Sensor TX), TX=17 (to Sensor RX)"));
  Serial.println(F("========================================="));

  Serial.println(F("Initializing GT-521F32 sensor..."));
  if (sensorOpen()) {
    Serial.println(F("PASS: GT-521F32 connected successfully."));
    Serial.println(F("Status: READY (Sensor LED idle OFF)."));
  } else {
    Serial.println(F("WARNING: GT-521F32 did not respond to OPEN."));
    Serial.println(F("Check 5V power, GND, TX/RX crossover, and 9600 baud."));
  }
  printHelpMenu();
}

void loop() {
  if (Serial.available()) {
    int peekChar = Serial.peek();

    // Check if this is the start of an LLFP binary frame ('L' = 0x4C)
    if (peekChar == 'L') {
      // Need at least 28-byte header to validate LLFP
      if (Serial.available() >= 28) {
        uint8_t header[28];
        Serial.readBytes(header, 28);

        if (header[0] == 'L' && header[1] == 'L' && header[2] == 'F' && header[3] == 'P') {
          uint8_t reqId[16];
          memcpy(reqId, &header[6], 16);
          uint16_t cmd = uint16_t(header[22]) | (uint16_t(header[23]) << 8);
          uint16_t payloadLen = uint16_t(header[26]) | (uint16_t(header[27]) << 8);

          uint8_t payloadBuf[512];
          if (payloadLen > 0) {
            size_t rec = 0;
            uint32_t t0 = millis();
            while (rec < payloadLen && millis() - t0 < 1000) {
              if (Serial.available()) payloadBuf[rec++] = Serial.read();
            }
          }

          // Read 4 bytes CRC
          uint8_t crcBuf[4];
          size_t recCrc = 0;
          uint32_t t1 = millis();
          while (recCrc < 4 && millis() - t1 < 500) {
            if (Serial.available()) crcBuf[recCrc++] = Serial.read();
          }

          handleLLFPCommand(cmd, reqId, payloadBuf, payloadLen);
          return;
        }
      }
    }

    // Otherwise, treat as ASCII command from Serial Monitor
    char c = char(Serial.read());
    if (c == 's' || c == 'S') {
      interactiveScan();
    } else if (c == 'e' || c == 'E') {
      interactiveEnroll();
    } else if (c == 'v' || c == 'V') {
      interactiveVerify();
    } else if (c == 'c' || c == 'C') {
      Serial.println(F("\nClearing scratch slots (199 and 0)..."));
      sensorDeleteSlot(SCRATCH_SLOT);
      sensorDeleteSlot(0);
      Serial.println(F("Scratch slots cleared. Ready for fresh enrollment."));
    } else if (c == 'd' || c == 'D') {
      Serial.println(F("\nDeleting ALL stored fingerprints from sensor memory..."));
      if (sensorDeleteAll()) {
        Serial.println(F("PASS: All sensor slots successfully wiped."));
      } else {
        Serial.println(F("FAIL: Failed to delete all slots."));
      }
    } else if (c == 'l' || c == 'L') {
      sensorSetLed(!ledState);
      Serial.printf("Sensor LED is now %s.\n", ledState ? "ON" : "OFF");
    } else if (c == 'r' || c == 'R') {
      Serial.println(F("\nReconnecting to GT-521F32..."));
      if (sensorOpen()) {
        Serial.println(F("PASS: Sensor reconnected successfully."));
      } else {
        Serial.println(F("FAIL: Reconnection unsuccessful. Check wiring."));
      }
    } else if (c == 'h' || c == 'H') {
      printHelpMenu();
    }
  }
}

