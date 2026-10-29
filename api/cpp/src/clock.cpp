#include "apriltag/clock.hpp"

#include <algorithm>

namespace apriltag {

void ClockSync::add_sample(double t0, double t1, uint64_t device_us, uint32_t tick_hz) {
    if (t1 < t0) throw Error("t1 < t0");
    if (samples_.size() == max_) samples_.pop_front();
    samples_.push_back(Sample{(t0 + t1) / 2, double(device_us) / tick_hz, t1 - t0});
}

void ClockSync::sample(Camera& cam, int n) {
    for (int i = 0; i < n; i++) {
        TimeSample s = cam.get_time_sample();
        add_sample(s.t0, s.t1, s.time.now_us, s.time.tick_hz);
    }
}

double ClockSync::best_rtt() const {
    double m = -1;
    for (const Sample& s : samples_) m = m < 0 ? s.rtt : std::min(m, s.rtt);
    return m;
}

ClockSync::Model ClockSync::model() const {
    if (samples_.empty()) throw Error("no clock samples");
    const Sample* best = &samples_.front();
    for (const Sample& s : samples_) if (s.rtt < best->rtt) best = &s;
    Model m{best->dev_s, best->host_mid, 1.0};
    if (fit_ && samples_.size() >= 3) {
        std::vector<const Sample*> use;
        for (const Sample& s : samples_) if (s.rtt <= 2 * best->rtt + 1e-9) use.push_back(&s);
        if (use.size() >= 3) {
            double xm = 0, ym = 0;
            for (auto* s : use) { xm += s->dev_s; ym += s->host_mid; }
            xm /= double(use.size());
            ym /= double(use.size());
            double sxx = 0, sxy = 0;
            for (auto* s : use) { sxx += (s->dev_s - xm) * (s->dev_s - xm); sxy += (s->dev_s - xm) * (s->host_mid - ym); }
            if (sxx > 0) m = Model{xm, ym, sxy / sxx};
        }
    }
    return m;
}

double ClockSync::offset_s() const { Model m = model(); return m.host_ref - m.dev_ref; }
double ClockSync::skew_ppm() const { return (model().slope - 1.0) * 1e6; }

double ClockSync::to_host(uint64_t device_us, uint32_t tick_hz) const {
    Model m = model();
    return m.host_ref + (double(device_us) / tick_hz - m.dev_ref) * m.slope;
}

double ClockSync::to_device_us(double host_s, uint32_t tick_hz) const {
    Model m = model();
    return (m.dev_ref + (host_s - m.host_ref) / m.slope) * tick_hz;
}

}  // namespace apriltag
