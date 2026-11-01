#include "apriltag/camera.hpp"

#include <algorithm>
#include <chrono>

namespace apriltag {
using namespace proto;

static double steady_now() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

Camera::Camera(std::unique_ptr<Transport> t, Clock clock) : t_(std::move(t)), clock_(clock ? std::move(clock) : Clock(steady_now)) {
    const uint8_t zero = 0;
    t_->write(&zero, 1);   // resynchronise the device's frame parser
}

Camera Camera::open_serial(const std::string& port) { return Camera(std::make_unique<SerialTransport>(port)); }

bool Camera::pump(double timeout_s) {
    uint8_t buf[4096];
    size_t n = t_->read(buf, sizeof buf, timeout_s);
    if (n == 0) return false;
    for (Frame& f : dec_.feed(buf, n)) {
        if (f.type == RSP_POSE) {
            Pose p;
            if (!decode_pose(f.body, p)) {
                frames_ignored++;
                continue;
            }
            poses_.push_back(p);
            if (poses_.size() > 1024) poses_.pop_front();
        }
        inbox_.push_back(std::move(f));
    }
    return true;
}

// Sends and waits for the matching response; POSE frames received meanwhile are queued. NAK -> NakError, silence is
// retried (commands are idempotent) and finally TimeoutError.
Bytes Camera::request(uint8_t cmd, const Bytes& body, uint8_t rsp, double timeout_s, int retries) {
    for (int attempt = 0; attempt <= retries; attempt++) {
        inbox_.clear();
        Bytes frame = encode_frame(cmd, body);
        t_->write(frame.data(), frame.size());
        double deadline = now() + timeout_s;
        for (;;) {
            while (!inbox_.empty()) {
                Frame f = std::move(inbox_.front());
                inbox_.pop_front();
                if (f.type == RSP_NAK && f.body.size() >= 2 && f.body[0] == cmd) throw NakError(cmd, f.body[1]);
                if (f.type == rsp && (rsp != RSP_ACK || (!f.body.empty() && f.body[0] == cmd))) return f.body;
                if (f.type != RSP_POSE) frames_ignored++;
            }
            double remaining = deadline - now();
            if (remaining <= 0) break;
            pump(std::min(remaining, 0.05));
        }
    }
    char msg[80];
    std::snprintf(msg, sizeof msg, "no response to command 0x%02X after %d attempts", cmd, retries + 1);
    throw TimeoutError(msg);
}

PingResult Camera::ping() {
    double t0 = now();
    Bytes b = request(CMD_PING, Bytes{'p', 'i', 'n', 'g'}, RSP_PONG);
    if (b.size() != 12) throw Error("bad PONG length");
    return PingResult{get_u32(&b[4]), get_u32(&b[8]), now() - t0};
}

void Camera::set_calibration(const Calibration& c) {
    Bytes b;
    for (double v : {c.fx, c.fy, c.cx, c.cy}) put_f32(b, float(v));
    for (double v : c.dist) put_f32(b, float(v));
    ack(CMD_SET_CALIB, b);
}

void Camera::clear_map() { ack(CMD_CLEAR_MAP); }

void Camera::add_tag(const TagDef& t) {
    Bytes b;
    put_u16(b, t.id);
    put_f32(b, float(t.size));
    for (double v : t.position) put_f32(b, float(v));
    for (double v : t.quat_wxyz) put_f32(b, float(v));
    ack(CMD_ADD_TAG, b);
}

void Camera::commit() { request(CMD_COMMIT, {}, RSP_ACK, std::max(timeout_s, 3.0), retries); }

Config Camera::get_config() {
    Bytes b = request(CMD_GET_CONFIG, {}, RSP_CONFIG);
    if (b.size() != CONFIG_LEN) throw Error("bad CONFIG length");
    Config c;
    c.calibration.fx = get_f32(&b[0]);
    c.calibration.fy = get_f32(&b[4]);
    c.calibration.cx = get_f32(&b[8]);
    c.calibration.cy = get_f32(&b[12]);
    for (int i = 0; i < 5; i++) c.calibration.dist[i] = get_f32(&b[16 + 4 * i]);
    unsigned n = get_u16(&b[36]);
    for (unsigned i = 0; i < n; i++) c.tags.push_back(get_tag(uint16_t(i)));
    return c;
}

TagDef Camera::get_tag(uint16_t index) {
    Bytes req;
    put_u16(req, index);
    Bytes b = request(CMD_GET_TAG, req, RSP_TAG);
    if (b.size() != TAG_LEN) throw Error("bad TAG length");
    TagDef t;
    t.id = get_u16(&b[0]);
    t.size = get_f32(&b[4]);
    for (int i = 0; i < 3; i++) t.position[i] = get_f32(&b[8 + 4 * i]);
    for (int i = 0; i < 4; i++) t.quat_wxyz[i] = get_f32(&b[20 + 4 * i]);
    return t;
}

void Camera::stream(bool enable, uint16_t divider) {
    Bytes b{uint8_t(enable ? 1 : 0)};
    put_u16(b, divider);
    ack(CMD_STREAM, b);
}

void Camera::set_sensor(uint16_t exposure, uint8_t gain) {
    Bytes b;
    put_u16(b, exposure);
    b.push_back(gain);
    ack(CMD_SET_SENSOR, b);
}

void Camera::set_ae(bool enable) { ack(CMD_SET_AE, Bytes{uint8_t(enable ? 1 : 0)}); }

void Camera::set_auto_ratio(bool enable) { ack(CMD_SET_AUTO_RATIO, Bytes{uint8_t(enable ? 1 : 0)}); }

void Camera::set_track(uint8_t diff, uint8_t abs_black, uint8_t mindim, uint8_t maxham, uint8_t ratio) {
    if (maxham > 63) throw Error("maxham out of range");
    if (ratio > 3) throw Error("ratio out of range");
    ack(CMD_SET_TRACK, Bytes{diff, abs_black, mindim, uint8_t(maxham | (ratio << 6))});
}

Status Camera::get_status() {
    Status s;
    if (!decode_status(request(CMD_GET_STATUS, {}, RSP_STATUS), s)) throw Error("bad STATUS length");
    return s;
}

Pose Camera::get_pose() {
    Pose p;
    if (!decode_pose(request(CMD_GET_POSE, {}, RSP_POSE), p)) throw Error("bad POSE length");
    return p;
}

TagsRaw Camera::get_tags_raw() {
    Bytes b = request(CMD_GET_TAGS_RAW, {}, RSP_TAGS);
    if (b.size() < 5 || b.size() < 5 + 35u * b[4]) throw Error("bad TAGS length");
    TagsRaw r;
    r.frame_id = get_u32(&b[0]);
    for (unsigned i = 0; i < b[4]; i++) {
        const uint8_t* o = &b[5 + 35 * i];
        RawTag t;
        t.id = get_u16(o);
        t.hamming = o[2];
        for (int k = 0; k < 4; k++) {
            t.corners[k][0] = get_f32(o + 3 + 8 * k);
            t.corners[k][1] = get_f32(o + 7 + 8 * k);
        }
        r.tags.push_back(t);
    }
    return r;
}

TimeSample Camera::get_time_sample() {
    TimeSample s;
    s.t0 = now();
    Bytes b = request(CMD_GET_TIME, {}, RSP_TIME, timeout_s, 0);
    s.t1 = now();
    if (!decode_time(b, s.time)) throw Error("bad TIME length");
    return s;
}

std::optional<Pose> Camera::poll_pose(double timeout_s) {
    double deadline = now() + timeout_s;
    for (;;) {
        if (!poses_.empty()) {
            Pose p = poses_.front();
            poses_.pop_front();
            return p;
        }
        inbox_.clear();
        double remaining = deadline - now();
        if (remaining <= 0) {
            pump(0);
            if (poses_.empty()) return std::nullopt;
            continue;
        }
        pump(std::min(remaining, 0.05));
    }
}

Camera::PoseStream::PoseStream(Camera& c, uint16_t divider, double timeout_s) : c_(&c), timeout_(timeout_s) { c.stream(true, divider); }

Camera::PoseStream::~PoseStream() {
    if (!c_) return;
    try {
        c_->stream(false, 1);
    } catch (...) {
    }
}

Pose Camera::PoseStream::next() {
    auto p = c_->poll_pose(timeout_);
    if (!p) throw TimeoutError("no pose within timeout");
    return *p;
}

void Camera::on_pose(uint16_t divider, double timeout_s, const std::function<bool(const Pose&)>& cb) {
    PoseStream s = poses(divider, timeout_s);
    while (cb(s.next())) {
    }
}

}  // namespace apriltag
