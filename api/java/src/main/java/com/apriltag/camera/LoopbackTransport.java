package com.apriltag.camera;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

/** In-memory transport. The optional handler (a fake device) sees every write and returns bytes to make readable. */
public class LoopbackTransport implements Transport {
    private final Function<byte[], byte[]> handler;
    private final ByteArrayOutputStream rx = new ByteArrayOutputStream();
    private byte[] pending = new byte[0];
    private int pos;
    public final List<byte[]> written = new ArrayList<>();

    public LoopbackTransport() {
        this(null);
    }

    public LoopbackTransport(Function<byte[], byte[]> handler) {
        this.handler = handler;
    }

    /** Queues device-originated bytes (streamed frames, garbage, ...). */
    public synchronized void inject(byte[] data) {
        rx.write(data, 0, data.length);
    }

    @Override
    public synchronized void write(byte[] data) {
        written.add(data.clone());
        if (handler != null) {
            byte[] out = handler.apply(data.clone());
            if (out != null) rx.write(out, 0, out.length);
        }
    }

    @Override
    public synchronized int read(byte[] buf, double timeoutS) {
        if (pos >= pending.length) {
            pending = rx.toByteArray();
            rx.reset();
            pos = 0;
        }
        if (pending.length == 0) {
            try {
                Thread.sleep(Math.min((long) (timeoutS * 1000), 1));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            return 0;
        }
        int n = Math.min(buf.length, pending.length - pos);
        System.arraycopy(pending, pos, buf, 0, n);
        pos += n;
        return n;
    }

    @Override
    public void close() {}
}
