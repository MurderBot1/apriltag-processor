package com.apriltag.camera;

import java.io.IOException;

/** Byte link to the camera. Implement this to plug in any serial library. */
public interface Transport extends AutoCloseable {
    void write(byte[] data) throws IOException;

    /** Reads up to buf.length bytes, waiting at most timeoutS seconds; returns 0 on timeout. */
    int read(byte[] buf, double timeoutS) throws IOException;

    @Override
    void close() throws IOException;
}
