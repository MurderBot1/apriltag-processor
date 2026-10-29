// Byte transports: abstract Transport, in-memory loopback, and a native serial port (Win32 COM / POSIX termios).
#pragma once
#include <deque>
#include <functional>
#include <memory>
#include <string>

#include "apriltag/protocol.hpp"

namespace apriltag {

class Transport {
public:
    virtual ~Transport() = default;
    virtual void write(const uint8_t* data, size_t len) = 0;
    // Reads up to max_len bytes, waiting at most timeout_s; returns 0 on timeout. Throws Error on I/O failure.
    virtual size_t read(uint8_t* buf, size_t max_len, double timeout_s) = 0;
};

// In-memory transport. The optional handler (a fake device) sees every write and returns bytes to make readable.
class LoopbackTransport : public Transport {
public:
    using Handler = std::function<Bytes(const Bytes&)>;
    explicit LoopbackTransport(Handler h = nullptr) : handler_(std::move(h)) {}
    void inject(const Bytes& data) { rx_.insert(rx_.end(), data.begin(), data.end()); }
    void write(const uint8_t* data, size_t len) override;
    size_t read(uint8_t* buf, size_t max_len, double timeout_s) override;
    std::vector<Bytes> written;

private:
    Handler handler_;
    std::deque<uint8_t> rx_;
};

// COM port ("COM5", "\\\\.\\COM12") on Windows, tty path ("/dev/ttyACM0") on POSIX. Baud rate is irrelevant for USB CDC.
class SerialTransport : public Transport {
public:
    explicit SerialTransport(const std::string& port, unsigned baud = 115200);
    ~SerialTransport() override;
    SerialTransport(const SerialTransport&) = delete;
    SerialTransport& operator=(const SerialTransport&) = delete;
    void write(const uint8_t* data, size_t len) override;
    size_t read(uint8_t* buf, size_t max_len, double timeout_s) override;

private:
    struct Impl;
    std::unique_ptr<Impl> p_;
};

}  // namespace apriltag
