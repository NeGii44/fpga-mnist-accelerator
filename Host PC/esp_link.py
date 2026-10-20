"""Shared serial link: send one 784-byte image to the ESP32, read back the FPGA digit."""
import re, time
import serial

SYNC = bytes([0xA5, 0x5A])
PAT = re.compile(rb"Prediction Result:\s*(\d+)")

def open_port(port, baud=115200):
    # dtr/rts False so opening the port does not reset the ESP32
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, baud, 0.2
    ser.dtr = False
    ser.rts = False
    ser.open()
    time.sleep(0.3)
    return ser

def predict(ser, pixels784, timeout=5.0):
    """pixels784: bytes/bytearray/list of 784 ints, each 0-127. Returns digit int or None."""
    data = bytes(pixels784)
    assert len(data) == 784 and max(data) <= 127, "need 784 values in 0..127"
    ser.reset_input_buffer()
    ser.write(SYNC + data)
    ser.flush()
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        buf += ser.read(256)
        m = PAT.search(buf)
        if m:
            return int(m.group(1))
    return None
