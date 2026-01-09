# modbus.py — MicroPython helpers for Modbus RTU Master over RS-485
from machine import UART, Pin
import time

DEFAULT_DIR_SW_US = 400
DEFAULT_TIMEOUT_MS = 500
DEFAULT_INTERFRAME_MS = 1

def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if (crc & 1):
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class RS485:
    def __init__(self, uart_id, baudrate, tx_pin, rx_pin,
                 use_dir=False, de_re_pin=None, dir_sw_us=DEFAULT_DIR_SW_US):
        self.uart = UART(
            uart_id,
            baudrate=baudrate,
            bits=8,
            parity=None,
            stop=1,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
        )
        self.use_dir = bool(use_dir)
        self.dir_sw_us = int(dir_sw_us)

        self.de_re = None
        if self.use_dir:
            if de_re_pin is None:
                raise ValueError("use_dir=True but no de_re_pin given")
            self.de_re = Pin(de_re_pin, Pin.OUT)
            self.de_re.value(0)  # default RX mode

    def _tx_mode(self):
        if self.use_dir:
            self.de_re.value(1)
            time.sleep_us(self.dir_sw_us)

    def _rx_mode(self):
        if self.use_dir:
            time.sleep_us(self.dir_sw_us)
            self.de_re.value(0)

    def write(self, buf: bytes):
        self._tx_mode()
        self.uart.write(buf)
        self._rx_mode()

    def any(self):
        return self.uart.any()

    def read(self):
        return self.uart.read()

    def rx_flush(self):
        if self.uart.any():
            try:
                self.uart.read()
            except:
                pass


class ModbusRTUMaster:
    def __init__(self, rs485, timeout_ms=DEFAULT_TIMEOUT_MS,
                 interframe_ms=DEFAULT_INTERFRAME_MS, debug=False):
        self.rs485 = rs485
        self.timeout_ms = timeout_ms
        self.interframe_ms = interframe_ms
        self.debug = debug

    def _send_and_recv(self, req, expected_len):
        if self.debug:
            print("TX:", req.hex())

        self.rs485.rx_flush()
        self.rs485.write(req)

        buf = b""
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < self.timeout_ms:
            if self.rs485.any():
                data = self.rs485.read()
                if data:
                    buf += data
                    if len(buf) >= expected_len:
                        break
            time.sleep_ms(self.interframe_ms)

        if len(buf) < expected_len:
            raise OSError("Timeout %d/%d" % (len(buf), expected_len))

        if self.debug:
            print("RX:", buf.hex())
        return buf

    def read_holding_registers(self, slave, start_addr, quantity):
        req = bytes([
            slave & 0xFF, 0x03,
            (start_addr >> 8) & 0xFF, start_addr & 0xFF,
            (quantity >> 8) & 0xFF, quantity & 0xFF,
        ])
        c = crc16(req)
        req = req + bytes([c & 0xFF, (c >> 8) & 0xFF])

        expected = 5 + quantity * 2
        resp = self._send_and_recv(req, expected)

        data = resp[:-2]
        crc_lo = resp[-2]
        crc_hi = resp[-1]
        calc = crc16(data)

        if (calc & 0xFF) != crc_lo or ((calc >> 8) & 0xFF) != crc_hi:
            raise ValueError("CRC mismatch")

        if data[0] != slave or data[1] != 0x03:
            raise ValueError("Invalid slave or func")

        byte_count = data[2]
        if byte_count != quantity * 2:
            raise ValueError("ByteCount mismatch")

        payload = data[3:]
        regs = [(payload[i] << 8) | payload[i+1] for i in range(0, byte_count, 2)]
        return regs
