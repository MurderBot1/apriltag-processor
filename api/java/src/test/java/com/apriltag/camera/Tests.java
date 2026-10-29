package com.apriltag.camera;

import static com.apriltag.camera.Protocol.*;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Random;

/** Dependency-free test runner: java -cp out com.apriltag.camera.Tests [path/to/golden_frames.txt] */
public class Tests {
    static int passed, failed;
    static String goldenPath = "../testdata/golden_frames.txt";

    interface Body { void run() throws Exception; }

    static void test(String name, Body b) {
        try {
            b.run();
            passed++;
            System.out.println("ok   " + name);
        } catch (Throwable e) {
            failed++;
            System.out.println("FAIL " + name + ": " + e);
            e.printStackTrace(System.out);
        }
    }

    static void check(boolean c, String msg) {
        if (!c) throw new AssertionError(msg);
    }

    static void near(double a, double b, double tol, String msg) {
        if (!(Math.abs(a - b) <= tol)) throw new AssertionError(msg + ": " + a + " vs " + b + " (tol " + tol + ")");
    }

    static byte[] hex(String s) {
        if (s.equals("-")) return new byte[0];
        byte[] b = new byte[s.length() / 2];
        for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return b;
    }

    record Golden(String name, int type, byte[] body, byte[] frame) {}

    static Map<String, Golden> golden() throws Exception {
        Map<String, Golden> m = new LinkedHashMap<>();
        for (String l : Files.readAllLines(Path.of(goldenPath))) {
            String[] p = l.split(" ");
            m.put(p[0], new Golden(p[0], Integer.parseInt(p[1]), hex(p[2]), hex(p[3])));
        }
        return m;
    }

    // ------------------------------------------------------------------------------------ fake device
    static class VClock {
        double t = 100.0;
    }

    static class FakeDevice {
        final VClock clk;
        final double t0, skew;
        final long offsetUs;
        final double[] lats;
        int calls;
        boolean streaming;
        final FrameDecoder dec = new FrameDecoder();

        FakeDevice(VClock clk, long offsetUs, double skew, double... lats) {
            this.clk = clk;
            this.t0 = clk.t;
            this.offsetUs = offsetUs;
            this.skew = skew;
            this.lats = lats.length > 0 ? lats : new double[] {0.001};
        }

        long devUs() {
            return (long) (offsetUs + (clk.t - t0) * (1 + skew) * 1e6);
        }

        byte[] poseFrame() {
            ByteBuffer b = le(new byte[POSE_LEN]);
            b.putInt(1).putInt(500).put((byte) 1).put((byte) 4).putShort((short) 1);
            for (float v : new float[] {1, 2, 3, 1, 0, 0, 0, 0.5f}) b.putFloat(v);
            b.putLong(devUs());
            return encodeFrame(RSP_POSE, b.array());
        }

        byte[] handle(byte[] data) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            for (Frame f : dec.feed(data)) {
                int typ = f.type();
                double lat = lats[calls++ % lats.length];
                clk.t += lat;
                byte[] pre = streaming ? poseFrame() : new byte[0];
                byte[] rsp;
                if (typ == CMD_GET_TIME) {
                    ByteBuffer b = le(new byte[TIME_LEN]);
                    b.putLong(devUs()).putLong(devUs() - 1000).putInt(1_000_000);
                    rsp = encodeFrame(RSP_TIME, b.array());
                } else if (typ == CMD_PING) {
                    ByteBuffer b = le(new byte[12]);
                    b.put(f.body(), 0, 4).putInt(0x10000).putInt(0x41544731);
                    rsp = encodeFrame(RSP_PONG, b.array());
                } else if (typ == CMD_STREAM) {
                    streaming = f.body()[0] == 1;
                    rsp = encodeFrame(RSP_ACK, new byte[] {(byte) typ});
                } else if (typ == CMD_GET_POSE) {
                    rsp = encodeFrame(RSP_NAK, new byte[] {(byte) typ, ERR_NO_POSE});
                } else if (typ == CMD_SET_SENSOR && f.body()[0] == 0 && f.body()[1] == 0) {
                    rsp = encodeFrame(RSP_NAK, new byte[] {(byte) typ, ERR_RANGE});
                } else {
                    rsp = encodeFrame(RSP_ACK, new byte[] {(byte) typ});
                }
                out.writeBytes(pre);
                out.writeBytes(rsp);
                clk.t += lat;
            }
            return out.toByteArray();
        }
    }

    record Rig(Camera cam, FakeDevice dev, LoopbackTransport tr, VClock clk) {}

    static Rig rig(long offsetUs, double skew, double... lats) throws Exception {
        VClock clk = new VClock();
        FakeDevice dev = new FakeDevice(clk, offsetUs, skew, lats);
        LoopbackTransport tr = new LoopbackTransport(dev::handle);
        return new Rig(new Camera(tr, () -> clk.t), dev, tr, clk);
    }

    // ------------------------------------------------------------------------------------ tests
    public static void main(String[] args) throws Exception {
        if (args.length > 0) goldenPath = args[0];

        test("crc check value", () -> check(crc16("123456789".getBytes()) == 0x29B1, "crc"));

        test("cobs roundtrip", () -> {
            List<byte[]> cases = new ArrayList<>();
            cases.add(new byte[0]);
            cases.add(new byte[] {0});
            cases.add(new byte[2]);
            cases.add("abc".getBytes());
            byte[] r254 = new byte[254], r255 = new byte[255];
            for (int i = 0; i < 254; i++) r254[i] = (byte) (i + 1);
            for (int i = 0; i < 255; i++) r255[i] = (byte) (i + 1);
            cases.add(r254);
            cases.add(r255);
            for (int n : new int[] {253, 254, 255, 508}) {
                byte[] a = new byte[n];
                Arrays.fill(a, (byte) 1);
                cases.add(a);
            }
            byte[] mid = new byte[256];
            Arrays.fill(mid, (byte) 7);
            mid[0] = 0;
            mid[255] = 0;
            cases.add(mid);
            cases.add(new byte[300]);
            for (byte[] c : cases) {
                byte[] e = cobsEncode(c);
                for (byte b : e) check(b != 0, "zero in encoded");
                check(Arrays.equals(cobsDecode(e, e.length), c), "roundtrip len " + c.length);
            }
            byte[] ones = new byte[254];
            Arrays.fill(ones, (byte) 1);
            check((cobsEncode(ones)[0] & 0xFF) == 0xFF, "0xFF code");
        });

        test("golden frames encode/decode", () -> {
            for (Golden g : golden().values()) {
                check(Arrays.equals(encodeFrame(g.type(), g.body()), g.frame()), "encode " + g.name());
                List<Frame> fs = new FrameDecoder().feed(g.frame());
                check(fs.size() == 1 && fs.get(0).type() == g.type() && Arrays.equals(fs.get(0).body(), g.body()), "decode " + g.name());
            }
        });

        test("decode POSE / TIME / STATUS", () -> {
            Map<String, Golden> g = golden();
            Frame f = new FrameDecoder().feed(g.get("pose").frame()).get(0);
            Pose p = decodePose(f.body());
            check(f.type() == 0x82 && p.frameId() == 1234 && p.processingUs() == 777 && p.ntags() == 2 && p.flags() == 1 && p.nobs() == 5, "pose fields");
            check(Arrays.equals(p.position(), new float[] {1.5f, -2.25f, 0.5f}), "position");
            check(p.timestampUs() == 0x0123456789ABL, "timestamp");
            TimeInfo t = decodeTime(g.get("time").body());
            check(t.nowUs() == 5_000_000_000L && t.frameUs() == 4_999_000_000L && t.tickHz() == 1_000_000, "time");
            Status s = decodeStatus(g.get("status").body());
            check(s.frameId() == 4242 && s.ntags() == 3 && s.poseValid() && s.streaming() && s.exposure() == 400 && s.gain() == 0x20
                    && s.aeEnabled() && s.meanBrightness() == 110.0 && s.fpgaSeq() == 5, "status");
            check(decodePose(new byte[44]) == null, "short pose rejected");
        });

        test("decoder resilience", () -> {
            byte[] fr = golden().get("pose").frame();
            byte[] bad = fr.clone();
            bad[3] ^= 0x55;
            ByteArrayOutputStream in = new ByteArrayOutputStream();
            in.writeBytes(new byte[] {0x13, 0x37, 'g', 'a', 'r', 0});
            in.writeBytes(bad);
            in.write(0);
            in.write(0);
            in.writeBytes(fr);
            byte[] big = new byte[400];
            Arrays.fill(big, (byte) 1);
            in.writeBytes(big);
            in.write(0);
            in.writeBytes(Arrays.copyOf(fr, 5));
            FrameDecoder d = new FrameDecoder();
            List<Frame> out = new ArrayList<>(d.feed(in.toByteArray()));
            out.addAll(d.feed(Arrays.copyOfRange(fr, 5, fr.length)));
            check(out.size() == 2 && out.get(0).type() == 0x82 && out.get(1).type() == 0x82, "two good frames, got " + out.size());
            check(d.badFrames >= 3, "bad frames counted: " + d.badFrames);
        });

        test("leading zero and ping", () -> {
            Rig r = rig(0, 0);
            check(Arrays.equals(r.tr().written.get(0), new byte[] {0}), "lone zero first");
            Camera.PingResult p = r.cam().ping();
            check(p.firmwareVersion() == 0x10000 && p.fpgaId() == 0x41544731L, "ping");
        });

        test("NAK is a typed error", () -> {
            Rig r = rig(0, 0);
            try {
                r.cam().getPose();
                check(false, "expected NAK");
            } catch (CameraException.Nak e) {
                check(e.code == ERR_NO_POSE && e.cmd == CMD_GET_POSE, "nak fields");
            }
            try {
                r.cam().setSensor(0, 0x10);
                check(false, "expected NAK");
            } catch (CameraException.Nak e) {
                check(e.code == ERR_RANGE, "range");
            }
        });

        test("interleaved streaming", () -> {
            Rig r = rig(7_000_000, 0);
            Camera c = r.cam();
            c.stream(true, 2);
            c.setAe(true);
            c.setTrack(24, 64, 10, 2);
            c.addTag(1, 0.1, new double[3], new double[] {1, 0, 0, 0});
            check(c.getTime().tickHz() == 1_000_000, "tick_hz");
            int n = 0;
            Pose p;
            while ((p = c.pollPose(0)) != null) {
                check(p.timestampUs() > 0, "timestamp");
                n++;
            }
            check(n == 4, "queued poses " + n);
            r.tr().inject(r.dev().poseFrame());
            check(c.pollPose(0.01) != null, "injected pose");
        });

        test("pose iterator disables stream", () -> {
            Rig r = rig(0, 0);
            r.tr().inject(concat(r.dev().poseFrame(), r.dev().poseFrame(), r.dev().poseFrame()));
            try (Camera.PoseStream s = r.cam().poses(1, 0.05)) {
                s.next();
                s.next();
            }
            check(!r.dev().streaming, "stream off");
            int[] cnt = {0};
            r.tr().inject(concat(r.dev().poseFrame(), r.dev().poseFrame()));
            r.cam().onPose(1, 0.05, pp -> ++cnt[0] < 2);
            check(cnt[0] == 2 && !r.dev().streaming, "callback");
        });

        test("timeout and retry", () -> {
            LoopbackTransport t = new LoopbackTransport();
            Camera c = new Camera(t);
            c.timeoutS = 0.02;
            c.retries = 1;
            try {
                c.ping();
                check(false, "expected timeout");
            } catch (CameraException.Timeout e) {
                check(t.written.size() == 3, "writes " + t.written.size());
            }
            boolean[] drop = {true};
            LoopbackTransport t2 = new LoopbackTransport(w -> {
                if (drop[0]) {
                    drop[0] = false;
                    return null;
                }
                return encodeFrame(RSP_PONG, new byte[12]);
            });
            Camera c2 = new Camera(t2);
            c2.timeoutS = 0.02;
            c2.ping();
        });

        test("ClockSync offset and skew", () -> {
            Rig r = rig(7_000_000, 200e-6, 0.001, 0.0003, 0.002, 0.0003);
            ClockSync cs = new ClockSync();
            for (int i = 0; i < 40; i++) {
                cs.sample(r.cam(), 1);
                r.clk().t += 0.1;
            }
            near(cs.bestRtt(), 0.0006, 1e-6, "best rtt");
            near(cs.skewPpm(), (1 / (1 + 200e-6) - 1) * 1e6, 5, "skew ppm");
            long dev = r.dev().devUs();
            near(cs.toHost(dev, 1_000_000), r.clk().t, 50e-6, "to_host");
            near(cs.toDeviceUs(r.clk().t, 1_000_000), dev, 50, "to_device");
            ClockSync nofit = new ClockSync(64, false).sample(r.cam(), 8);
            near(nofit.toHost(r.dev().devUs(), 1_000_000), r.clk().t, nofit.bestRtt() / 2 + 1e-6, "no-fit");
        });

        test("ClockSync pose timestamp", () -> {
            Rig r = rig(123_456_789L, 0, 0.001);
            ClockSync cs = new ClockSync().sample(r.cam(), 8);
            r.clk().t += 0.5;
            Pose p = decodePose(new FrameDecoder().feed(r.dev().poseFrame()).get(0).body());
            near(cs.poseHostTime(p), r.clk().t, 1e-5, "pose host time");
        });

        test("ClockSync synthetic jitter", () -> {
            ClockSync cs = new ClockSync();
            Random rnd = new Random(1);
            double skew = 1 - 50e-6;
            for (int i = 0; i < 50; i++) {
                double h = 10.0 + i * 0.05, rtt = 0.0004 + rnd.nextDouble() * 0.004;
                cs.addSample(h - rtt / 2, h + rtt / 2, Math.round((3.0 + (h - 10.0) / skew) * 1e6), 1_000_000);
            }
            near(cs.toHost(Math.round((3.0 + 5.0 / skew) * 1e6), 1_000_000), 15.0, 0.002, "synthetic");
        });

        System.out.println(passed + " passed, " + failed + " failed");
        System.exit(failed == 0 ? 0 : 1);
    }

    static byte[] concat(byte[]... parts) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        for (byte[] p : parts) o.writeBytes(p);
        return o.toByteArray();
    }
}
