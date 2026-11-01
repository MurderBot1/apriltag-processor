// High level camera API over a Transport. Not thread-safe; use one thread per Camera.
#pragma once
#include <deque>
#include <functional>
#include <memory>
#include <optional>

#include "apriltag/protocol.hpp"
#include "apriltag/transport.hpp"

namespace apriltag {

struct Calibration {
    double fx, fy, cx, cy;
    std::array<double, 5> dist{};   // k1, k2, p1, p2, k3
};

struct TagDef {
    uint16_t id;
    double size;
    std::array<double, 3> position;
    std::array<double, 4> quat_wxyz;
};

struct Config {
    Calibration calibration;
    std::vector<TagDef> tags;
};

struct RawTag {
    uint16_t id;
    uint8_t hamming;
    float corners[4][2];   // TL, TR, BR, BL
};

struct TagsRaw {
    uint32_t frame_id;
    std::vector<RawTag> tags;
};

struct PingResult {
    uint32_t firmware_version, fpga_id;
    double rtt_s;
};

// GET_TIME exchange: host clock before send (t0) and after receive (t1), plus the device reply.
struct TimeSample {
    double t0, t1;
    proto::TimeInfo time;
};

using proto::Pose;
using proto::Status;
using proto::TimeInfo;

class Camera {
public:
    using Clock = std::function<double()>;   // host seconds, monotonic

    // Sends the lone 0x00 resync byte. Default clock: std::chrono::steady_clock.
    explicit Camera(std::unique_ptr<Transport> t, Clock clock = nullptr);
    static Camera open_serial(const std::string& port);

    double timeout_s = 1.0;
    int retries = 2;
    unsigned frames_ignored = 0;

    double now() const { return clock_(); }
    Transport& transport() { return *t_; }

    PingResult ping();
    void set_calibration(const Calibration& c);
    void clear_map();
    void add_tag(const TagDef& t);
    void commit();
    Config get_config();
    TagDef get_tag(uint16_t index);
    void stream(bool enable, uint16_t divider = 1);
    // Manual exposure (lines, 1..800) and gain register (0x10 = 1x); disables auto exposure.
    void set_sensor(uint16_t exposure, uint8_t gain = 0x10);
    void set_ae(bool enable);
    void set_track(uint8_t diff = 24, uint8_t abs_black = 64, uint8_t mindim = 10, uint8_t maxham = 2, uint8_t ratio = 0);   // ratio: tile contrast test 0: 2x, 1: 3x, 2: 4x, 3: off
    Status get_status();
    Pose get_pose();   // NakError(ERR_NO_POSE) if none yet
    TagsRaw get_tags_raw();
    TimeSample get_time_sample();   // no retries, to keep the RTT honest
    TimeInfo get_time() { return get_time_sample().time; }

    // Next queued streamed pose, waiting up to timeout_s.
    std::optional<Pose> poll_pose(double timeout_s = 0);

    // RAII pose stream: enables streaming now, disables it on destruction. next() throws TimeoutError on silence.
    class PoseStream {
    public:
        PoseStream(Camera& c, uint16_t divider, double timeout_s);
        PoseStream(PoseStream&& o) noexcept : c_(o.c_), timeout_(o.timeout_) { o.c_ = nullptr; }
        PoseStream(const PoseStream&) = delete;
        ~PoseStream();
        Pose next();

    private:
        Camera* c_;
        double timeout_;
    };
    PoseStream poses(uint16_t divider = 1, double timeout_s = 1.0) { return PoseStream(*this, divider, timeout_s); }

    // Callback style: streams until the callback returns false.
    void on_pose(uint16_t divider, double timeout_s, const std::function<bool(const Pose&)>& cb);

private:
    bool pump(double timeout_s);
    Bytes request(uint8_t cmd, const Bytes& body, uint8_t rsp, double timeout_s, int retries);
    Bytes request(uint8_t cmd, const Bytes& body, uint8_t rsp) { return request(cmd, body, rsp, timeout_s, retries); }
    void ack(uint8_t cmd, const Bytes& body = {}) { request(cmd, body, proto::RSP_ACK); }

    std::unique_ptr<Transport> t_;
    Clock clock_;
    proto::FrameDecoder dec_;
    std::deque<Pose> poses_;
    std::deque<proto::Frame> inbox_;
};

}  // namespace apriltag
