#include "apriltag/transport.hpp"

#include <algorithm>
#include <chrono>
#include <thread>

#ifdef _WIN32
#include <windows.h>
#else
#include <errno.h>
#include <fcntl.h>
#include <sys/select.h>
#include <termios.h>
#include <unistd.h>
#endif

namespace apriltag {

void LoopbackTransport::write(const uint8_t* data, size_t len) {
    written.emplace_back(data, data + len);
    if (handler_) inject(handler_(written.back()));
}

size_t LoopbackTransport::read(uint8_t* buf, size_t max_len, double timeout_s) {
    if (rx_.empty()) {
        std::this_thread::sleep_for(std::chrono::duration<double>(std::min(timeout_s, 0.001)));
        return 0;
    }
    size_t n = std::min(max_len, rx_.size());
    for (size_t i = 0; i < n; i++) {
        buf[i] = rx_.front();
        rx_.pop_front();
    }
    return n;
}

#ifdef _WIN32

struct SerialTransport::Impl {
    HANDLE h = INVALID_HANDLE_VALUE;
};

SerialTransport::SerialTransport(const std::string& port, unsigned baud) : p_(new Impl) {
    std::string path = port.rfind("\\\\.\\", 0) == 0 ? port : "\\\\.\\" + port;
    p_->h = CreateFileA(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (p_->h == INVALID_HANDLE_VALUE) throw Error("cannot open " + port);
    DCB dcb{};
    dcb.DCBlength = sizeof dcb;
    if (GetCommState(p_->h, &dcb)) {
        dcb.BaudRate = baud;
        dcb.ByteSize = 8;
        dcb.Parity = NOPARITY;
        dcb.StopBits = ONESTOPBIT;
        dcb.fBinary = TRUE;
        dcb.fOutxCtsFlow = dcb.fOutxDsrFlow = FALSE;
        dcb.fDtrControl = DTR_CONTROL_ENABLE;      // many CDC firmwares only talk once DTR is asserted
        dcb.fRtsControl = RTS_CONTROL_ENABLE;
        dcb.fOutX = dcb.fInX = FALSE;
        SetCommState(p_->h, &dcb);
    }
    PurgeComm(p_->h, PURGE_RXCLEAR | PURGE_TXCLEAR);
}

SerialTransport::~SerialTransport() {
    if (p_ && p_->h != INVALID_HANDLE_VALUE) CloseHandle(p_->h);
}

void SerialTransport::write(const uint8_t* data, size_t len) {
    size_t off = 0;
    while (off < len) {
        DWORD n = 0;
        if (!WriteFile(p_->h, data + off, DWORD(len - off), &n, nullptr)) throw Error("serial write failed");
        off += n;
    }
}

size_t SerialTransport::read(uint8_t* buf, size_t max_len, double timeout_s) {
    // MAXDWORD/MAXDWORD/ms: return as soon as any byte is available, otherwise wait at most ms.
    COMMTIMEOUTS to{};
    to.ReadIntervalTimeout = MAXDWORD;
    to.ReadTotalTimeoutMultiplier = MAXDWORD;
    to.ReadTotalTimeoutConstant = DWORD(std::max(1.0, timeout_s * 1000.0));
    to.WriteTotalTimeoutConstant = 2000;
    SetCommTimeouts(p_->h, &to);
    DWORD n = 0;
    if (!ReadFile(p_->h, buf, DWORD(max_len), &n, nullptr)) throw Error("serial read failed");
    return n;
}

#else

struct SerialTransport::Impl {
    int fd = -1;
};

SerialTransport::SerialTransport(const std::string& port, unsigned) : p_(new Impl) {
    p_->fd = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (p_->fd < 0) throw Error("cannot open " + port);
    termios tio{};
    if (tcgetattr(p_->fd, &tio) == 0) {
        cfmakeraw(&tio);
        tio.c_cflag |= CLOCAL | CREAD;
        tcsetattr(p_->fd, TCSANOW, &tio);
    }
    tcflush(p_->fd, TCIOFLUSH);
}

SerialTransport::~SerialTransport() {
    if (p_ && p_->fd >= 0) ::close(p_->fd);
}

void SerialTransport::write(const uint8_t* data, size_t len) {
    size_t off = 0;
    while (off < len) {
        ssize_t n = ::write(p_->fd, data + off, len - off);
        if (n < 0) {
            if (errno == EAGAIN || errno == EINTR) {
                fd_set w;
                FD_ZERO(&w);
                FD_SET(p_->fd, &w);
                timeval tv{2, 0};
                select(p_->fd + 1, nullptr, &w, nullptr, &tv);
                continue;
            }
            throw Error("serial write failed");
        }
        off += size_t(n);
    }
}

size_t SerialTransport::read(uint8_t* buf, size_t max_len, double timeout_s) {
    fd_set r;
    FD_ZERO(&r);
    FD_SET(p_->fd, &r);
    timeval tv;
    tv.tv_sec = long(timeout_s);
    tv.tv_usec = long((timeout_s - double(tv.tv_sec)) * 1e6);
    int s = select(p_->fd + 1, &r, nullptr, nullptr, &tv);
    if (s < 0) {
        if (errno == EINTR) return 0;
        throw Error("serial select failed");
    }
    if (s == 0) return 0;
    ssize_t n = ::read(p_->fd, buf, max_len);
    if (n < 0) {
        if (errno == EAGAIN || errno == EINTR) return 0;
        throw Error("serial read failed");
    }
    return size_t(n);
}

#endif

}  // namespace apriltag
