import time
import threading

import serial
from shared.singleton import Singleton

class SerialComm(metaclass=Singleton):
    def __init__(self, port="COM3", baudrate=9600, timeout=0.1, startup_delay=2.0):
        self.lock = threading.RLock()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.startup_delay = startup_delay
        self.ser = None
        self._connect()

    def _connect(self):
        with self.lock:
            if self.ser and self.ser.is_open:
                return

            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=1,
            )
            time.sleep(self.startup_delay)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

    def send(self, msg):
        with self.lock:
            self._connect()
            self.ser.write((msg.strip() + "\n").encode("utf-8"))
            self.ser.flush()

    def receive(self):
        with self.lock:
            self._connect()
            if self.ser.in_waiting <= 0:
                return None
            data = self.ser.readline().decode("utf-8", errors="ignore").strip()
            return data.lower() or None
