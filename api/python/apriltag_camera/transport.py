"""Byte transports: pyserial (optional dependency) and an in-memory loopback for tests."""
import time


class Transport:
    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def read(self, max_bytes: int, timeout: float) -> bytes:
        """Returns up to max_bytes (b'' on timeout)."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class SerialTransport(Transport):
    def __init__(self, port, baud=115200):
        import serial                     # pip install pyserial
        self.ser = serial.Serial(port, baud, timeout=0, write_timeout=2)

    def write(self, data):
        self.ser.write(data)
        self.ser.flush()

    def read(self, max_bytes, timeout):
        deadline = time.monotonic() + timeout
        while True:
            n = self.ser.in_waiting
            if n:
                return self.ser.read(min(n, max_bytes))
            if time.monotonic() >= deadline:
                return b''
            time.sleep(0.0005)

    def close(self):
        self.ser.close()


class LoopbackTransport(Transport):
    """In-memory transport. `handler(written_bytes)` (a fake device) may return bytes to make readable;
    inject() queues device-originated bytes (streamed POSE frames, garbage, ...)."""

    def __init__(self, handler=None):
        self.handler = handler
        self.rx = bytearray()
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(bytes(data))
        if self.handler:
            out = self.handler(bytes(data))
            if out:
                self.rx += out

    def inject(self, data):
        self.rx += data

    def read(self, max_bytes, timeout):
        if not self.rx:
            time.sleep(min(timeout, 0.001))
            return b''
        out = bytes(self.rx[:max_bytes])
        del self.rx[:max_bytes]
        return out

    def close(self):
        self.closed = True
