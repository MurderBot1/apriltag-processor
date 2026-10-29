package com.apriltag.camera;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Wire protocol: CRC16, COBS framing, message encode/decode (see docs/protocol.md). */
public final class Protocol {
    private Protocol() {}

    public static final int MAX_BODY = 256, MAX_FRAME = MAX_BODY + 8;

    public static final int CMD_PING = 0x01, CMD_SET_CALIB = 0x02, CMD_CLEAR_MAP = 0x03, CMD_ADD_TAG = 0x04, CMD_COMMIT = 0x05,
            CMD_GET_CONFIG = 0x06, CMD_STREAM = 0x07, CMD_SET_SENSOR = 0x08, CMD_GET_STATUS = 0x09, CMD_SET_TRACK = 0x0A,
            CMD_GET_POSE = 0x0B, CMD_GET_TAG = 0x0C, CMD_GET_TAGS_RAW = 0x0D, CMD_SET_AE = 0x0E, CMD_GET_TIME = 0x0F;
    public static final int RSP_ACK = 0x80, RSP_PONG = 0x81, RSP_POSE = 0x82, RSP_TAGS = 0x83, RSP_CONFIG = 0x86, RSP_TAG = 0x87,
            RSP_STATUS = 0x89, RSP_TIME = 0x8A, RSP_NAK = 0xFF;
    public static final int ERR_BAD_LEN = 1, ERR_FULL = 2, ERR_FLASH = 3, ERR_UNKNOWN = 4, ERR_NO_POSE = 5, ERR_RANGE = 6;
    public static final int POSE_LEN = 52, STATUS_LEN = 48, TIME_LEN = 20, CONFIG_LEN = 40, TAG_LEN = 36;

    public static String errName(int code) {
        String[] n = {"?", "BAD_LEN", "FULL", "FLASH", "UNKNOWN", "NO_POSE", "RANGE"};
        return code >= 1 && code <= 6 ? n[code] : "?";
    }

    /** CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). */
    public static int crc16(byte[] d, int off, int len) {
        int c = 0xFFFF;
        for (int i = off; i < off + len; i++) {
            c ^= (d[i] & 0xFF) << 8;
            for (int k = 0; k < 8; k++) c = (c & 0x8000) != 0 ? ((c << 1) ^ 0x1021) & 0xFFFF : (c << 1) & 0xFFFF;
        }
        return c;
    }

    public static int crc16(byte[] d) {
        return crc16(d, 0, d.length);
    }

    public static byte[] cobsEncode(byte[] raw) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(raw.length + raw.length / 254 + 2);
        byte[] blk = new byte[254];
        int n = 0;
        for (byte b : raw) {
            if (b == 0) {
                out.write(n + 1);
                out.write(blk, 0, n);
                n = 0;
            } else {
                blk[n++] = b;
                if (n == 254) {
                    out.write(0xFF);
                    out.write(blk, 0, n);
                    n = 0;
                }
            }
        }
        out.write(n + 1);
        out.write(blk, 0, n);
        return out.toByteArray();
    }

    /** Returns null on malformed input. */
    public static byte[] cobsDecode(byte[] enc, int len) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(len);
        int i = 0;
        while (i < len) {
            int code = enc[i++] & 0xFF;
            if (code == 0 || i + code - 1 > len) return null;
            out.write(enc, i, code - 1);
            i += code - 1;
            if (code != 0xFF && i < len) out.write(0);
        }
        return out.toByteArray();
    }

    public static byte[] encodeFrame(int type, byte[] body) {
        if (body.length > MAX_BODY) throw new IllegalArgumentException("body too large");
        byte[] raw = new byte[body.length + 3];
        raw[0] = (byte) type;
        System.arraycopy(body, 0, raw, 1, body.length);
        int c = crc16(raw, 0, body.length + 1);
        raw[raw.length - 2] = (byte) c;
        raw[raw.length - 1] = (byte) (c >> 8);
        byte[] enc = cobsEncode(raw);
        return Arrays.copyOf(enc, enc.length + 1);      // trailing 0x00 delimiter
    }

    public record Frame(int type, byte[] body) {}

    /** Incremental decoder; garbage, bad CRC and oversized frames are dropped and counted. */
    public static final class FrameDecoder {
        private final byte[] buf = new byte[MAX_FRAME];
        private int len;
        private boolean overflow;
        public int badFrames, goodFrames;

        public List<Frame> feed(byte[] data, int n) {
            List<Frame> out = new ArrayList<>();
            for (int i = 0; i < n; i++) {
                byte b = data[i];
                if (b != 0) {
                    if (len < MAX_FRAME) buf[len++] = b;
                    else overflow = true;
                    continue;
                }
                int l = len;
                boolean ovf = overflow;
                len = 0;
                overflow = false;
                if (l == 0) continue;
                byte[] dec = ovf ? null : cobsDecode(buf, l);
                if (dec == null || dec.length < 3
                        || crc16(dec, 0, dec.length - 2) != ((dec[dec.length - 2] & 0xFF) | (dec[dec.length - 1] & 0xFF) << 8)) {
                    badFrames++;
                    continue;
                }
                goodFrames++;
                out.add(new Frame(dec[0] & 0xFF, Arrays.copyOfRange(dec, 1, dec.length - 2)));
            }
            return out;
        }

        public List<Frame> feed(byte[] data) {
            return feed(data, data.length);
        }
    }

    // ------------------------------------------------------------------------------------ messages
    public static ByteBuffer le(byte[] b) {
        return ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
    }

    public static final int FLAG_AMBIGUOUS = 1, FLAG_OUTLIER_DROPPED = 2, FLAG_SINGLE_TAG = 4;

    /** u32 fields are held in long; timestampUs is the device time in microseconds. */
    public record Pose(long frameId, long processingUs, int ntags, int flags, int nobs, float[] position, float[] quaternion,
                       float rmsPx, long timestampUs) {}

    public record TimeInfo(long nowUs, long frameUs, long tickHz) {}

    public record Status(long fpgaStatus, long ccl, long framesDropped, long framesTotal, long framesProcessed, long solved,
                         long solveFail, long tornReads, long frameId, int ntags, boolean poseValid, boolean streaming,
                         int exposure, int gain, boolean aeEnabled, double meanBrightness) {
        public boolean initDone() { return (fpgaStatus >> 3 & 1) != 0; }
        public boolean tpuBusy() { return (fpgaStatus >> 2 & 1) != 0; }
        public boolean resValid() { return (fpgaStatus & 1) != 0; }
        public int fpgaSeq() { return (int) (fpgaStatus >> 16 & 0xFFFF); }
    }

    /** Returns null if the length is wrong. */
    public static Pose decodePose(byte[] b) {
        if (b.length != POSE_LEN) return null;
        ByteBuffer v = le(b);
        return new Pose(v.getInt(0) & 0xFFFFFFFFL, v.getInt(4) & 0xFFFFFFFFL, b[8] & 0xFF, b[9] & 0xFF, v.getShort(10) & 0xFFFF,
                new float[] {v.getFloat(12), v.getFloat(16), v.getFloat(20)},
                new float[] {v.getFloat(24), v.getFloat(28), v.getFloat(32), v.getFloat(36)}, v.getFloat(40), v.getLong(44));
    }

    public static TimeInfo decodeTime(byte[] b) {
        if (b.length != TIME_LEN) return null;
        ByteBuffer v = le(b);
        return new TimeInfo(v.getLong(0), v.getLong(8), v.getInt(16) & 0xFFFFFFFFL);
    }

    public static Status decodeStatus(byte[] b) {
        if (b.length != STATUS_LEN) return null;
        ByteBuffer v = le(b);
        long[] w = new long[9];
        for (int i = 0; i < 9; i++) w[i] = v.getInt(4 * i) & 0xFFFFFFFFL;
        return new Status(w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8], v.getShort(36) & 0xFFFF, b[38] != 0, b[39] != 0,
                v.getShort(40) & 0xFFFF, b[42] & 0xFF, b[43] != 0, (v.getShort(44) & 0xFFFF) / 256.0);
    }
}
