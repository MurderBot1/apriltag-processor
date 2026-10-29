package com.apriltag.camera;

import static com.apriltag.camera.Protocol.*;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.function.DoubleSupplier;
import java.util.function.Predicate;

/** High level camera API over a {@link Transport}. Not thread-safe; use one thread per Camera. */
public class Camera implements AutoCloseable {
    public record Calibration(double fx, double fy, double cx, double cy, double[] dist) {}

    public record TagDef(int id, double size, double[] position, double[] quatWxyz) {}

    public record Config(Calibration calibration, List<TagDef> tags) {}

    public record RawTag(int id, int hamming, float[][] corners) {}

    public record TagsRaw(long frameId, List<RawTag> tags) {}

    public record PingResult(long firmwareVersion, long fpgaId, double rttS) {}

    public record TimeSample(double t0, double t1, TimeInfo time) {}

    private final Transport t;
    private final DoubleSupplier clock;
    private final FrameDecoder dec = new FrameDecoder();
    private final ArrayDeque<Pose> poses = new ArrayDeque<>();
    private final ArrayDeque<Frame> inbox = new ArrayDeque<>();
    public double timeoutS = 1.0;
    public int retries = 2;
    public int framesIgnored;

    /** Host clock in seconds, used for timeouts, RTTs and ClockSync (default System.nanoTime). */
    public Camera(Transport t, DoubleSupplier clock) throws IOException {
        this.t = t;
        this.clock = clock;
        t.write(new byte[] {0});            // resynchronise the device's frame parser
    }

    public Camera(Transport t) throws IOException {
        this(t, () -> System.nanoTime() / 1e9);
    }

    /** Opens a CDC serial port by path using plain java.io (see {@link StreamTransport}). */
    public static Camera openPort(String path) throws IOException {
        return new Camera(StreamTransport.openPort(path));
    }

    public double now() {
        return clock.getAsDouble();
    }

    @Override
    public void close() throws IOException {
        t.close();
    }

    // ------------------------------------------------------------------------------------ framing
    private boolean pump(double timeoutS) throws IOException {
        byte[] buf = new byte[4096];
        int n = t.read(buf, timeoutS);
        if (n <= 0) return false;
        for (Frame f : dec.feed(buf, n)) {
            if (f.type() == RSP_POSE) {
                Pose p = decodePose(f.body());
                if (p == null) {
                    framesIgnored++;
                    continue;
                }
                poses.addLast(p);
                if (poses.size() > 1024) poses.removeFirst();
            }
            inbox.addLast(f);
        }
        return true;
    }

    /** Sends and waits for the matching response; POSE frames received meanwhile are queued. NAK -> CameraException.Nak,
     * silence is retried (commands are idempotent) and finally CameraException.Timeout. */
    private byte[] request(int cmd, byte[] body, int rsp, double timeoutS, int retries) throws IOException {
        for (int attempt = 0; attempt <= retries; attempt++) {
            inbox.clear();
            t.write(encodeFrame(cmd, body));
            double deadline = now() + timeoutS;
            while (true) {
                while (!inbox.isEmpty()) {
                    Frame f = inbox.removeFirst();
                    byte[] b = f.body();
                    if (f.type() == RSP_NAK && b.length >= 2 && (b[0] & 0xFF) == cmd) throw new CameraException.Nak(cmd, b[1] & 0xFF);
                    if (f.type() == rsp && (rsp != RSP_ACK || (b.length >= 1 && (b[0] & 0xFF) == cmd))) return b;
                    if (f.type() != RSP_POSE) framesIgnored++;
                }
                double remaining = deadline - now();
                if (remaining <= 0) break;
                pump(Math.min(remaining, 0.05));
            }
        }
        throw new CameraException.Timeout(String.format("no response to command 0x%02X after %d attempts", cmd, retries + 1));
    }

    private byte[] request(int cmd, byte[] body, int rsp) throws IOException {
        return request(cmd, body, rsp, timeoutS, retries);
    }

    private void ack(int cmd, byte[] body) throws IOException {
        request(cmd, body, RSP_ACK);
    }

    private static ByteBuffer buf(int n) {
        return ByteBuffer.allocate(n).order(java.nio.ByteOrder.LITTLE_ENDIAN);
    }

    // ------------------------------------------------------------------------------------ commands
    public PingResult ping() throws IOException {
        double t0 = now();
        byte[] b = request(CMD_PING, "ping".getBytes(), RSP_PONG);
        if (b.length != 12) throw new CameraException("bad PONG length");
        ByteBuffer v = le(b);
        return new PingResult(v.getInt(4) & 0xFFFFFFFFL, v.getInt(8) & 0xFFFFFFFFL, now() - t0);
    }

    /** dist = k1, k2, p1, p2, k3 (missing entries are 0). */
    public void setCalibration(Calibration c) throws IOException {
        ByteBuffer b = buf(36);
        b.putFloat((float) c.fx()).putFloat((float) c.fy()).putFloat((float) c.cx()).putFloat((float) c.cy());
        for (int i = 0; i < 5; i++) b.putFloat(c.dist() != null && i < c.dist().length ? (float) c.dist()[i] : 0f);
        ack(CMD_SET_CALIB, b.array());
    }

    public void clearMap() throws IOException {
        ack(CMD_CLEAR_MAP, new byte[0]);
    }

    public void addTag(int id, double size, double[] position, double[] quatWxyz) throws IOException {
        ByteBuffer b = buf(34);
        b.putShort((short) id).putFloat((float) size);
        for (int i = 0; i < 3; i++) b.putFloat((float) position[i]);
        for (int i = 0; i < 4; i++) b.putFloat((float) quatWxyz[i]);
        ack(CMD_ADD_TAG, b.array());
    }

    public void commit() throws IOException {
        request(CMD_COMMIT, new byte[0], RSP_ACK, Math.max(timeoutS, 3.0), retries);
    }

    public Config getConfig() throws IOException {
        byte[] b = request(CMD_GET_CONFIG, new byte[0], RSP_CONFIG);
        if (b.length != CONFIG_LEN) throw new CameraException("bad CONFIG length");
        ByteBuffer v = le(b);
        double[] dist = new double[5];
        for (int i = 0; i < 5; i++) dist[i] = v.getFloat(16 + 4 * i);
        int n = v.getShort(36) & 0xFFFF;
        List<TagDef> tags = new ArrayList<>();
        for (int i = 0; i < n; i++) tags.add(getTag(i));
        return new Config(new Calibration(v.getFloat(0), v.getFloat(4), v.getFloat(8), v.getFloat(12), dist), tags);
    }

    public TagDef getTag(int index) throws IOException {
        byte[] b = request(CMD_GET_TAG, buf(2).putShort((short) index).array(), RSP_TAG);
        if (b.length != TAG_LEN) throw new CameraException("bad TAG length");
        ByteBuffer v = le(b);
        return new TagDef(v.getShort(0) & 0xFFFF, v.getFloat(4), new double[] {v.getFloat(8), v.getFloat(12), v.getFloat(16)},
                new double[] {v.getFloat(20), v.getFloat(24), v.getFloat(28), v.getFloat(32)});
    }

    public void stream(boolean enable, int divider) throws IOException {
        ack(CMD_STREAM, buf(3).put((byte) (enable ? 1 : 0)).putShort((short) divider).array());
    }

    /** Manual exposure (lines, 1..800) and gain register (0x10 = 1x); disables auto exposure. */
    public void setSensor(int exposure, int gain) throws IOException {
        ack(CMD_SET_SENSOR, buf(3).putShort((short) exposure).put((byte) gain).array());
    }

    public void setAe(boolean enable) throws IOException {
        ack(CMD_SET_AE, new byte[] {(byte) (enable ? 1 : 0)});
    }

    /** Reset values 24, 64, 10, 2. */
    public void setTrack(int diff, int absBlack, int mindim, int maxham) throws IOException {
        if (maxham > 63 || diff < 0 || diff > 255 || absBlack < 0 || absBlack > 255 || mindim < 0 || mindim > 255 || maxham < 0) {
            throw new IllegalArgumentException("tracking parameter out of range");
        }
        ack(CMD_SET_TRACK, new byte[] {(byte) diff, (byte) absBlack, (byte) mindim, (byte) maxham});
    }

    public Status getStatus() throws IOException {
        Status s = decodeStatus(request(CMD_GET_STATUS, new byte[0], RSP_STATUS));
        if (s == null) throw new CameraException("bad STATUS length");
        return s;
    }

    /** Latest solved pose; CameraException.Nak with code ERR_NO_POSE if none yet. */
    public Pose getPose() throws IOException {
        Pose p = decodePose(request(CMD_GET_POSE, new byte[0], RSP_POSE));
        if (p == null) throw new CameraException("bad POSE length");
        return p;
    }

    public TagsRaw getTagsRaw() throws IOException {
        byte[] b = request(CMD_GET_TAGS_RAW, new byte[0], RSP_TAGS);
        ByteBuffer v = le(b);
        int n = b[4] & 0xFF;
        if (b.length < 5 + 35 * n) throw new CameraException("bad TAGS length");
        List<RawTag> tags = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            int o = 5 + 35 * i;
            float[][] c = new float[4][2];
            for (int k = 0; k < 4; k++) {
                c[k][0] = v.getFloat(o + 3 + 8 * k);
                c[k][1] = v.getFloat(o + 7 + 8 * k);
            }
            tags.add(new RawTag(v.getShort(o) & 0xFFFF, b[o + 2] & 0xFF, c));
        }
        return new TagsRaw(v.getInt(0) & 0xFFFFFFFFL, tags);
    }

    /** Host clock before send / after receive plus the device reply. No retries, to keep the RTT honest. */
    public TimeSample getTimeSample() throws IOException {
        double t0 = now();
        byte[] b = request(CMD_GET_TIME, new byte[0], RSP_TIME, timeoutS, 0);
        double t1 = now();
        TimeInfo ti = decodeTime(b);
        if (ti == null) throw new CameraException("bad TIME length");
        return new TimeSample(t0, t1, ti);
    }

    /** TimeInfo(nowUs, frameUs, tickHz). */
    public TimeInfo getTime() throws IOException {
        return getTimeSample().time();
    }

    // ------------------------------------------------------------------------------------ poses
    /** Next queued streamed pose, waiting up to timeoutS seconds; null if none arrived. */
    public Pose pollPose(double timeoutS) throws IOException {
        double deadline = now() + timeoutS;
        while (true) {
            if (!poses.isEmpty()) return poses.removeFirst();
            inbox.clear();
            double remaining = deadline - now();
            if (remaining <= 0) {
                pump(0);
                return poses.pollFirst();
            }
            pump(Math.min(remaining, 0.05));
        }
    }

    /** Iterator of streamed poses; streaming is switched off by close(). next() throws UncheckedIOException (Timeout) on silence. */
    public final class PoseStream implements Iterator<Pose>, AutoCloseable {
        private final double timeout;
        private boolean open = true;

        private PoseStream(double timeout) {
            this.timeout = timeout;
        }

        @Override
        public boolean hasNext() {
            return open;
        }

        @Override
        public Pose next() {
            if (!open) throw new NoSuchElementException();
            try {
                Pose p = pollPose(timeout);
                if (p == null) throw new CameraException.Timeout("no pose within " + timeout + " s");
                return p;
            } catch (IOException e) {
                throw new java.io.UncheckedIOException(e);
            }
        }

        @Override
        public void close() throws IOException {
            if (open) {
                open = false;
                stream(false, 1);
            }
        }
    }

    public PoseStream poses(int divider, double timeoutS) throws IOException {
        stream(true, divider);
        return new PoseStream(timeoutS);
    }

    /** Callback style: streams until the callback returns false. */
    public void onPose(int divider, double timeoutS, Predicate<Pose> cb) throws IOException {
        try (PoseStream s = poses(divider, timeoutS)) {
            while (s.hasNext() && cb.test(s.next())) { /* loop */ }
        }
    }
}
