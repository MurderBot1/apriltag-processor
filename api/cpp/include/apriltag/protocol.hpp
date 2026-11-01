// Wire protocol: CRC16, COBS framing, message encode/decode (see docs/protocol.md).
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace apriltag {

using Bytes = std::vector<uint8_t>;

namespace proto {

constexpr size_t MAX_BODY = 256, MAX_FRAME = MAX_BODY + 8;

enum Cmd : uint8_t {
    CMD_PING = 0x01, CMD_SET_CALIB = 0x02, CMD_CLEAR_MAP = 0x03, CMD_ADD_TAG = 0x04, CMD_COMMIT = 0x05,
    CMD_GET_CONFIG = 0x06, CMD_STREAM = 0x07, CMD_SET_SENSOR = 0x08, CMD_GET_STATUS = 0x09, CMD_SET_TRACK = 0x0A,
    CMD_GET_POSE = 0x0B, CMD_GET_TAG = 0x0C, CMD_GET_TAGS_RAW = 0x0D, CMD_SET_AE = 0x0E, CMD_GET_TIME = 0x0F,
    CMD_SET_AUTO_RATIO = 0x10,
};
enum Rsp : uint8_t {
    RSP_ACK = 0x80, RSP_PONG = 0x81, RSP_POSE = 0x82, RSP_TAGS = 0x83, RSP_CONFIG = 0x86, RSP_TAG = 0x87,
    RSP_STATUS = 0x89, RSP_TIME = 0x8A, RSP_NAK = 0xFF,
};
enum Err : uint8_t { ERR_BAD_LEN = 1, ERR_FULL = 2, ERR_FLASH = 3, ERR_UNKNOWN = 4, ERR_NO_POSE = 5, ERR_RANGE = 6 };

constexpr size_t POSE_LEN = 52, STATUS_LEN = 48, TIME_LEN = 20, CONFIG_LEN = 40, TAG_LEN = 36;
constexpr uint8_t FLAG_AMBIGUOUS = 1, FLAG_OUTLIER_DROPPED = 2, FLAG_SINGLE_TAG = 4;

const char* err_name(int code);

// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF).
uint16_t crc16(const uint8_t* data, size_t len);
inline uint16_t crc16(const Bytes& b) { return crc16(b.data(), b.size()); }

Bytes cobs_encode(const Bytes& raw);
// Returns false on malformed input.
bool cobs_decode(const uint8_t* enc, size_t len, Bytes& out);
// COBS(type | body | crc16) | 0x00
Bytes encode_frame(uint8_t type, const Bytes& body = {});

struct Frame {
    uint8_t type;
    Bytes body;
};

// Incremental decoder; garbage, bad CRC and oversized frames are dropped and counted.
class FrameDecoder {
public:
    std::vector<Frame> feed(const uint8_t* data, size_t len);
    std::vector<Frame> feed(const Bytes& b) { return feed(b.data(), b.size()); }
    unsigned bad_frames = 0, good_frames = 0;

private:
    Bytes buf_;
    bool overflow_ = false;
};

// ---------------------------------------------------------------------------- messages
struct Pose {
    uint32_t frame_id = 0;
    uint32_t processing_us = 0;
    uint8_t ntags = 0;
    uint8_t flags = 0;
    uint16_t nobs = 0;
    std::array<float, 3> position{};      // camera -> world (m)
    std::array<float, 4> quaternion{};    // w, x, y, z
    float rms_px = 0;
    uint64_t timestamp_us = 0;            // device clock at the start of the source frame
};

struct TimeInfo {
    uint64_t now_us = 0, frame_us = 0;
    uint32_t tick_hz = 1000000;
};

struct Status {
    uint32_t fpga_status, ccl, frames_dropped, frames_total, frames_processed, solved, solve_fail, torn_reads, frame_id;
    uint16_t ntags;
    bool pose_valid, streaming;
    uint16_t exposure;
    uint8_t gain;
    bool ae_enabled;
    double mean_brightness;
    bool init_done() const { return fpga_status >> 3 & 1; }
    bool tpu_busy() const { return fpga_status >> 2 & 1; }
    bool res_valid() const { return fpga_status & 1; }
    uint16_t fpga_seq() const { return uint16_t(fpga_status >> 16); }
};

// Each returns false if the body length is wrong.
bool decode_pose(const Bytes& body, Pose& out);
bool decode_time(const Bytes& body, TimeInfo& out);
bool decode_status(const Bytes& body, Status& out);

// little-endian helpers
uint16_t get_u16(const uint8_t* p);
uint32_t get_u32(const uint8_t* p);
uint64_t get_u64(const uint8_t* p);
float get_f32(const uint8_t* p);
void put_u16(Bytes& b, uint16_t v);
void put_u32(Bytes& b, uint32_t v);
void put_u64(Bytes& b, uint64_t v);
void put_f32(Bytes& b, float v);

}  // namespace proto

// ---------------------------------------------------------------------------- errors
class Error : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class TimeoutError : public Error {
public:
    explicit TimeoutError(const std::string& m) : Error(m) {}
};

class NakError : public Error {
public:
    NakError(int cmd, int code);
    int cmd, code;
};

}  // namespace apriltag
