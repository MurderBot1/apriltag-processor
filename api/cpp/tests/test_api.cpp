#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <map>
#include <sstream>

#include "apriltag/camera.hpp"
#include "apriltag/clock.hpp"

using namespace apriltag;
using namespace apriltag::proto;

static int g_passed = 0, g_failed = 0;
static std::string g_golden = "../testdata/golden_frames.txt";

#define CHECK(c) do { if (!(c)) throw std::runtime_error(std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #c); } while (0)
#define NEAR(a, b, tol) do { double a_ = (a), b_ = (b); if (!(std::fabs(a_ - b_) <= (tol))) \
    throw std::runtime_error(std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #a " ~ " #b " got " + std::to_string(a_) + " vs " + std::to_string(b_)); } while (0)

static void run(const char* name, const std::function<void()>& f) {
    try {
        f();
        g_passed++;
        std::printf("ok   %s\n", name);
    } catch (const std::exception& e) {
        g_failed++;
        std::printf("FAIL %s: %s\n", name, e.what());
    }
}

static Bytes hex(const std::string& s) {
    Bytes b;
    if (s == "-") return b;
    for (size_t i = 0; i + 1 < s.size(); i += 2) b.push_back(uint8_t(std::stoi(s.substr(i, 2), nullptr, 16)));
    return b;
}

struct Golden {
    int type;
    Bytes body, frame;
};

static std::map<std::string, Golden> golden() {
    std::ifstream f(g_golden);
    if (!f) throw std::runtime_error("cannot open " + g_golden);
    std::map<std::string, Golden> m;
    std::string line;
    while (std::getline(f, line)) {
        std::istringstream is(line);
        std::string name, type, body, frame;
        is >> name >> type >> body >> frame;
        if (name.empty()) continue;
        m[name] = Golden{std::stoi(type), hex(body), hex(frame)};
    }
    return m;
}

// ---------------------------------------------------------------------------- fake device
struct VClock {
    double t = 100.0;
};

struct FakeDevice {
    VClock* clk;
    double t0, skew;
    uint64_t offset_us;
    std::vector<double> lats;
    size_t calls = 0;
    bool streaming = false;
    FrameDecoder dec;

    FakeDevice(VClock* c, uint64_t off, double sk, std::vector<double> l = {0.001}) : clk(c), t0(c->t), skew(sk), offset_us(off), lats(std::move(l)) {}

    uint64_t dev_us() const { return uint64_t(double(offset_us) + (clk->t - t0) * (1 + skew) * 1e6); }

    Bytes pose_frame() const {
        Bytes b;
        put_u32(b, 1);
        put_u32(b, 500);
        b.push_back(1);
        b.push_back(4);
        put_u16(b, 1);
        for (float v : {1.f, 2.f, 3.f, 1.f, 0.f, 0.f, 0.f, 0.5f}) put_f32(b, v);
        put_u64(b, dev_us());
        return encode_frame(RSP_POSE, b);
    }

    Bytes handle(const Bytes& data) {
        Bytes out;
        for (const Frame& f : dec.feed(data)) {
            double lat = lats[calls++ % lats.size()];
            clk->t += lat;
            Bytes pre = streaming ? pose_frame() : Bytes();
            Bytes rsp;
            if (f.type == CMD_GET_TIME) {
                Bytes b;
                put_u64(b, dev_us());
                put_u64(b, dev_us() - 1000);
                put_u32(b, 1000000);
                rsp = encode_frame(RSP_TIME, b);
            } else if (f.type == CMD_PING) {
                Bytes b(f.body.begin(), f.body.begin() + 4);
                put_u32(b, 0x10000);
                put_u32(b, 0x41544731);
                rsp = encode_frame(RSP_PONG, b);
            } else if (f.type == CMD_STREAM) {
                streaming = f.body[0] == 1;
                rsp = encode_frame(RSP_ACK, {f.type});
            } else if (f.type == CMD_GET_POSE) {
                rsp = encode_frame(RSP_NAK, {f.type, ERR_NO_POSE});
            } else if (f.type == CMD_SET_SENSOR && f.body[0] == 0 && f.body[1] == 0) {
                rsp = encode_frame(RSP_NAK, {f.type, ERR_RANGE});
            } else {
                rsp = encode_frame(RSP_ACK, {f.type});
            }
            out.insert(out.end(), pre.begin(), pre.end());
            out.insert(out.end(), rsp.begin(), rsp.end());
            clk->t += lat;
        }
        return out;
    }
};

struct Rig {
    VClock clk;
    std::unique_ptr<FakeDevice> dev;
    LoopbackTransport* tr;
    std::unique_ptr<Camera> cam;
    Rig(uint64_t off, double skew, std::vector<double> lats = {0.001}) {
        dev.reset(new FakeDevice(&clk, off, skew, lats));
        auto t = std::make_unique<LoopbackTransport>([this](const Bytes& b) { return dev->handle(b); });
        tr = t.get();
        cam.reset(new Camera(std::move(t), [this] { return clk.t; }));
    }
};

template <class F>
static bool throws_nak(F f, int code) {
    try {
        f();
    } catch (const NakError& e) {
        return e.code == code;
    }
    return false;
}

int main(int argc, char** argv) {
    if (argc > 1) g_golden = argv[1];

    run("crc check value", [] {
        const char* s = "123456789";
        CHECK(crc16(reinterpret_cast<const uint8_t*>(s), 9) == 0x29B1);
    });

    run("cobs roundtrip", [] {
        std::vector<Bytes> cases{{}, {0}, {0, 0}, {'a', 'b', 'c'}};
        Bytes r254, r255;
        for (int i = 1; i <= 254; i++) r254.push_back(uint8_t(i));
        for (int i = 1; i <= 255; i++) r255.push_back(uint8_t(i));
        cases.push_back(r254);
        cases.push_back(r255);
        for (size_t n : {253u, 254u, 255u, 508u}) cases.push_back(Bytes(n, 1));
        Bytes mid(256, 7);
        mid[0] = mid[255] = 0;
        cases.push_back(mid);
        cases.push_back(Bytes(300, 0));
        for (const Bytes& c : cases) {
            Bytes e = cobs_encode(c), d;
            for (uint8_t b : e) CHECK(b != 0);
            CHECK(cobs_decode(e.data(), e.size(), d));
            CHECK(d == c);
        }
        CHECK(cobs_encode(Bytes(254, 1))[0] == 0xFF);
    });

    run("golden frames encode/decode", [] {
        for (auto& kv : golden()) {
            const Golden& g = kv.second;
            CHECK(encode_frame(uint8_t(g.type), g.body) == g.frame);
            FrameDecoder d;
            auto fs = d.feed(g.frame);
            CHECK(fs.size() == 1 && fs[0].type == g.type && fs[0].body == g.body);
        }
    });

    run("decode POSE / TIME / STATUS", [] {
        auto g = golden();
        FrameDecoder d;
        auto fs = d.feed(g["pose"].frame);
        CHECK(fs.size() == 1 && fs[0].type == 0x82);
        Pose p;
        CHECK(decode_pose(fs[0].body, p));
        CHECK(p.frame_id == 1234 && p.processing_us == 777 && p.ntags == 2 && p.flags == 1 && p.nobs == 5);
        CHECK(p.position[0] == 1.5f && p.position[1] == -2.25f && p.position[2] == 0.5f);
        CHECK(p.timestamp_us == 0x0123456789ABull);
        TimeInfo t;
        CHECK(decode_time(g["time"].body, t));
        CHECK(t.now_us == 5000000000ull && t.frame_us == 4999000000ull && t.tick_hz == 1000000);
        Status s;
        CHECK(decode_status(g["status"].body, s));
        CHECK(s.frame_id == 4242 && s.ntags == 3 && s.pose_valid && s.streaming && s.exposure == 400 && s.gain == 0x20 && s.ae_enabled);
        CHECK(s.mean_brightness == 110.0 && s.fpga_seq() == 5);
        CHECK(!decode_pose(Bytes(44), p));
    });

    run("decoder resilience", [] {
        Bytes fr = golden()["pose"].frame, bad = fr, in{0x13, 0x37, 'g', 0};
        bad[3] ^= 0x55;
        in.insert(in.end(), bad.begin(), bad.end());
        in.push_back(0);
        in.push_back(0);
        in.insert(in.end(), fr.begin(), fr.end());
        in.insert(in.end(), 400, 1);
        in.push_back(0);
        in.insert(in.end(), fr.begin(), fr.begin() + 5);
        FrameDecoder d;
        auto out = d.feed(in);
        auto out2 = d.feed(Bytes(fr.begin() + 5, fr.end()));
        out.insert(out.end(), out2.begin(), out2.end());
        CHECK(out.size() == 2 && out[0].type == 0x82 && out[1].type == 0x82);
        CHECK(d.bad_frames >= 3);
    });

    run("leading zero and ping", [] {
        Rig r(0, 0);
        CHECK(r.tr->written[0] == Bytes{0});
        PingResult p = r.cam->ping();
        CHECK(p.firmware_version == 0x10000 && p.fpga_id == 0x41544731);
    });

    run("NAK is a typed error", [] {
        Rig r(0, 0);
        CHECK(throws_nak([&] { r.cam->get_pose(); }, ERR_NO_POSE));
        CHECK(throws_nak([&] { r.cam->set_sensor(0, 0x10); }, ERR_RANGE));
    });

    run("interleaved streaming", [] {
        Rig r(7000000, 0);
        Camera& c = *r.cam;
        c.stream(true, 2);
        c.set_ae(true);
        c.set_track();
        c.add_tag(TagDef{1, 0.1, {0, 0, 0}, {1, 0, 0, 0}});
        CHECK(c.get_time().tick_hz == 1000000);
        int n = 0;
        while (auto p = c.poll_pose(0)) {
            CHECK(p->timestamp_us > 0);
            n++;
        }
        CHECK(n == 4);
        r.tr->inject(r.dev->pose_frame());
        CHECK(c.poll_pose(0.01).has_value());
    });

    run("pose stream disables streaming", [] {
        Rig r(0, 0);
        Bytes f = r.dev->pose_frame(), three;
        for (int i = 0; i < 3; i++) three.insert(three.end(), f.begin(), f.end());
        r.tr->inject(three);
        {
            auto s = r.cam->poses(1, 0.05);
            s.next();
            s.next();
        }
        CHECK(!r.dev->streaming);
        r.tr->inject(three);
        int cnt = 0;
        r.cam->on_pose(1, 0.05, [&](const Pose&) { return ++cnt < 2; });
        CHECK(cnt == 2 && !r.dev->streaming);
    });

    run("timeout and retry", [] {
        auto t = std::make_unique<LoopbackTransport>();
        LoopbackTransport* tp = t.get();
        Camera c(std::move(t));
        c.timeout_s = 0.02;
        c.retries = 1;
        bool timed_out = false;
        try {
            c.ping();
        } catch (const TimeoutError&) {
            timed_out = true;
        }
        CHECK(timed_out && tp->written.size() == 3);
        bool drop = true;
        Camera c2(std::make_unique<LoopbackTransport>([&](const Bytes&) {
            if (drop) { drop = false; return Bytes(); }
            return encode_frame(RSP_PONG, Bytes(12, 0));
        }));
        c2.timeout_s = 0.02;
        c2.ping();
    });

    run("ClockSync offset and skew", [] {
        Rig r(7000000, 200e-6, {0.001, 0.0003, 0.002, 0.0003});
        ClockSync cs;
        for (int i = 0; i < 40; i++) {
            cs.sample(*r.cam, 1);
            r.clk.t += 0.1;
        }
        NEAR(cs.best_rtt(), 0.0006, 1e-6);
        NEAR(cs.skew_ppm(), (1 / (1 + 200e-6) - 1) * 1e6, 5);
        uint64_t dev = r.dev->dev_us();
        NEAR(cs.to_host(dev), r.clk.t, 50e-6);
        NEAR(cs.to_device_us(r.clk.t), double(dev), 50);
        ClockSync nofit(64, false);
        nofit.sample(*r.cam, 8);
        NEAR(nofit.to_host(r.dev->dev_us()), r.clk.t, nofit.best_rtt() / 2 + 1e-6);
    });

    run("ClockSync pose timestamp", [] {
        Rig r(123456789, 0);
        ClockSync cs;
        cs.sample(*r.cam, 8);
        r.clk.t += 0.5;
        FrameDecoder d;
        Pose p;
        CHECK(decode_pose(d.feed(r.dev->pose_frame())[0].body, p));
        NEAR(cs.pose_host_time(p), r.clk.t, 1e-5);
    });

    run("ClockSync synthetic jitter", [] {
        ClockSync cs;
        uint64_t seed = 12345;
        double skew = 1 - 50e-6;
        for (int i = 0; i < 50; i++) {
            seed = seed * 6364136223846793005ull + 1442695040888963407ull;
            double rtt = 0.0004 + double(seed >> 33) / double(1ull << 31) * 0.004, h = 10.0 + i * 0.05;
            cs.add_sample(h - rtt / 2, h + rtt / 2, uint64_t(std::llround((3.0 + (h - 10.0) / skew) * 1e6)));
        }
        NEAR(cs.to_host(uint64_t(std::llround((3.0 + 5.0 / skew) * 1e6))), 15.0, 0.002);
    });

    std::printf("%d passed, %d failed\n", g_passed, g_failed);
    return g_failed ? 1 : 0;
}
