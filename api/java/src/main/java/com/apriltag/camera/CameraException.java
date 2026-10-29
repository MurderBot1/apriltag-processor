package com.apriltag.camera;

import java.io.IOException;

public class CameraException extends IOException {
    public CameraException(String msg) {
        super(msg);
    }

    /** No response after all retries. */
    public static class Timeout extends CameraException {
        public Timeout(String msg) {
            super(msg);
        }
    }

    /** The device answered with NAK. */
    public static class Nak extends CameraException {
        public final int cmd, code;

        public Nak(int cmd, int code) {
            super(String.format("device NAK for command 0x%02X: error %d (%s)", cmd, code, Protocol.errName(code)));
            this.cmd = cmd;
            this.code = code;
        }
    }
}
