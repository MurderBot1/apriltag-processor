"""Byte transports.  A transport exposes write(bytes), read(max_bytes, timeout) -> bytes (b'' on timeout), close()."""
import time


class Transport:
    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def read(self, max_bytes: int, timeout: float) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class SerialTransport(Transport):
    """USB CDC serial port via pyserial (baud rate is irrelevant for CDC but required by the API)."""
    def __init__(self, port: str, baudrate: int = 115200, write_timeout: float = 2.0):
        import serial  # imported lazily so the sim works without pyserial
        self._serial = serial.serial_for_url(port, baudrate=baudrate, timeout=0, write_timeout=write_timeout)   # also accepts loop:// etc.

    def write(self, data: bytes) -> None:
        self._serial.write(data)
        self._serial.flush()

    def read(self, max_bytes: int, timeout: float) -> bytes:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            n = self._serial.in_waiting
            if n:
                return self._serial.read(min(n, max_bytes))
            if time.monotonic() >= deadline:
                return b''
            time.sleep(0.0005)

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass
