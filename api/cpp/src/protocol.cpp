#include "apriltag/protocol.hpp"

#include <cstdio>
#include <cstring>

namespace apriltag {
namespace proto {

const char* err_name(int code) {
    static const char* n[] = {"?", "BAD_LEN", "FULL", "FLASH", "UNKNOWN", "NO_POSE", "RANGE"};
    return code >= 1 && code <= 6 ? n[code] : "?";
}

uint16_t crc16(const uint8_t* d, size_t len) {
    uint16_t c = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        c ^= uint16_t(d[i]) << 8;
        for (int k = 0; k < 8; k++) c = (c & 0x8000) ? uint16_t((c << 1) ^ 0x1021) : uint16_t(c << 1);
    }
    return c;
}

Bytes cobs_encode(const Bytes& raw) {
    Bytes out(1, 0);
    size_t code_pos = 0;
    uint8_t code = 1;
    for (uint8_t b : raw) {
        if (b == 0) {
            out[code_pos] = code;
            code_pos = out.size();
            out.push_back(0);
            code = 1;
        } else {
            out.push_back(b);
            if (++code == 0xFF) {
                out[code_pos] = code;
                code_pos = out.size();
                out.push_back(0);
                code = 1;
            }
        }
    }
    out[code_pos] = code;
    return out;
}

bool cobs_decode(const uint8_t* enc, size_t n, Bytes& out) {
    out.clear();
    size_t i = 0;
    while (i < n) {
        size_t code = enc[i++];
        if (code == 0 || i + code - 1 > n) return false;
        out.insert(out.end(), enc + i, enc + i + code - 1);
        i += code - 1;
        if (code != 0xFF && i < n) out.push_back(0);
    }
    return true;
}

Bytes encode_frame(uint8_t type, const Bytes& body) {
    if (body.size() > MAX_BODY) throw Error("body too large");
    Bytes raw;
    raw.push_back(type);
    raw.insert(raw.end(), body.begin(), body.end());
    put_u16(raw, crc16(raw));
    Bytes out = cobs_encode(raw);
    out.push_back(0);
    return out;
}

std::vector<Frame> FrameDecoder::feed(const uint8_t* data, size_t len) {
    std::vector<Frame> out;
    for (size_t i = 0; i < len; i++) {
        if (data[i] != 0) {
            if (buf_.size() < MAX_FRAME) buf_.push_back(data[i]);
            else overflow_ = true;
            continue;
        }
        Bytes enc;
        enc.swap(buf_);
        bool ovf = overflow_;
        overflow_ = false;
        if (enc.empty()) continue;
        Bytes dec;
        if (ovf || !cobs_decode(enc.data(), enc.size(), dec) || dec.size() < 3 ||
            crc16(dec.data(), dec.size() - 2) != get_u16(&dec[dec.size() - 2])) {
            bad_frames++;
            continue;
        }
        good_frames++;
        out.push_back(Frame{dec[0], Bytes(dec.begin() + 1, dec.end() - 2)});
    }
    return out;
}

uint16_t get_u16(const uint8_t* p) { return uint16_t(p[0] | p[1] << 8); }
uint32_t get_u32(const uint8_t* p) { return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24; }
uint64_t get_u64(const uint8_t* p) { return uint64_t(get_u32(p)) | uint64_t(get_u32(p + 4)) << 32; }
float get_f32(const uint8_t* p) {
    uint32_t u = get_u32(p);
    float f;
    std::memcpy(&f, &u, 4);
    return f;
}
void put_u16(Bytes& b, uint16_t v) { b.push_back(uint8_t(v)); b.push_back(uint8_t(v >> 8)); }
void put_u32(Bytes& b, uint32_t v) { put_u16(b, uint16_t(v)); put_u16(b, uint16_t(v >> 16)); }
void put_u64(Bytes& b, uint64_t v) { put_u32(b, uint32_t(v)); put_u32(b, uint32_t(v >> 32)); }
void put_f32(Bytes& b, float v) {
    uint32_t u;
    std::memcpy(&u, &v, 4);
    put_u32(b, u);
}

bool decode_pose(const Bytes& b, Pose& p) {
    if (b.size() != POSE_LEN) return false;
    const uint8_t* d = b.data();
    p.frame_id = get_u32(d);
    p.processing_us = get_u32(d + 4);
    p.ntags = d[8];
    p.flags = d[9];
    p.nobs = get_u16(d + 10);
    for (int i = 0; i < 3; i++) p.position[i] = get_f32(d + 12 + 4 * i);
    for (int i = 0; i < 4; i++) p.quaternion[i] = get_f32(d + 24 + 4 * i);
    p.rms_px = get_f32(d + 40);
    p.timestamp_us = get_u64(d + 44);
    return true;
}

bool decode_time(const Bytes& b, TimeInfo& t) {
    if (b.size() != TIME_LEN) return false;
    t.now_us = get_u64(b.data());
    t.frame_us = get_u64(b.data() + 8);
    t.tick_hz = get_u32(b.data() + 16);
    return true;
}

bool decode_status(const Bytes& b, Status& s) {
    if (b.size() != STATUS_LEN) return false;
    const uint8_t* d = b.data();
    s.fpga_status = get_u32(d);
    s.ccl = get_u32(d + 4);
    s.frames_dropped = get_u32(d + 8);
    s.frames_total = get_u32(d + 12);
    s.frames_processed = get_u32(d + 16);
    s.solved = get_u32(d + 20);
    s.solve_fail = get_u32(d + 24);
    s.torn_reads = get_u32(d + 28);
    s.frame_id = get_u32(d + 32);
    s.ntags = get_u16(d + 36);
    s.pose_valid = d[38] != 0;
    s.streaming = d[39] != 0;
    s.exposure = get_u16(d + 40);
    s.gain = d[42];
    s.ae_enabled = d[43] != 0;
    s.mean_brightness = get_u16(d + 44) / 256.0;
    return true;
}

}  // namespace proto

static std::string nak_msg(int cmd, int code) {
    char buf[96];
    std::snprintf(buf, sizeof buf, "device NAK for command 0x%02X: error %d (%s)", cmd, code, proto::err_name(code));
    return buf;
}

NakError::NakError(int c, int e) : Error(nak_msg(c, e)), cmd(c), code(e) {}

}  // namespace apriltag
