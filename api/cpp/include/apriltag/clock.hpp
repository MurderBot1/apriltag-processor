// Device -> host clock mapping from GET_TIME round trips.
#pragma once
#include <deque>

#include "apriltag/camera.hpp"

namespace apriltag {

// Keeps (host midpoint, device time, rtt) samples. The min-RTT sample gives the offset (error <= rtt/2); with `fit` and
// >= 3 low-RTT samples a linear fit also estimates the relative skew.
class ClockSync {
public:
    explicit ClockSync(size_t max_samples = 64, bool fit = true) : max_(max_samples), fit_(fit) {}

    // t0/t1: host clock seconds before send / after receive of a GET_TIME exchange.
    void add_sample(double t0, double t1, uint64_t device_us, uint32_t tick_hz = 1000000);
    // Runs n GET_TIME round trips.
    void sample(Camera& cam, int n = 16);

    size_t size() const { return samples_.size(); }
    double best_rtt() const;
    double offset_s() const;    // host - device seconds at the reference sample
    double skew_ppm() const;    // host seconds per device second, minus one, in ppm
    // Device ticks -> host seconds in the Camera clock domain.
    double to_host(uint64_t device_us, uint32_t tick_hz = 1000000) const;
    double to_device_us(double host_s, uint32_t tick_hz = 1000000) const;
    double pose_host_time(const Pose& p) const { return to_host(p.timestamp_us); }

private:
    struct Sample {
        double host_mid, dev_s, rtt;
    };
    struct Model {
        double dev_ref, host_ref, slope;
    };
    Model model() const;

    std::deque<Sample> samples_;
    size_t max_;
    bool fit_;
};

}  // namespace apriltag
