package com.apriltag.camera;

import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * Transport over plain java.io streams (no dependencies). A daemon thread performs the blocking reads so that read() can time out.
 * {@link #openPort} opens a CDC port by path ("\\\\.\\COM5" on Windows, "/dev/ttyACM0" on Linux); the baud rate is ignored by the
 * device, but on Linux/macOS the tty should be put in raw mode first (stty -F /dev/ttyACM0 raw -echo). For full port control
 * wrap a serial library's streams (e.g. jSerialComm's getInputStream/getOutputStream) in this class.
 */
public class StreamTransport implements Transport {
    private final InputStream in;
    private final OutputStream out;
    private final BlockingQueue<byte[]> queue = new LinkedBlockingQueue<>();
    private byte[] cur = new byte[0];
    private int pos;
    private volatile boolean closed;

    public StreamTransport(InputStream in, OutputStream out) {
        this.in = in;
        this.out = out;
        Thread t = new Thread(this::pump, "apriltag-rx");
        t.setDaemon(true);
        t.start();
    }

    public static StreamTransport openPort(String path) throws IOException {
        return new StreamTransport(new FileInputStream(path), new FileOutputStream(path));
    }

    private void pump() {
        byte[] b = new byte[4096];
        try {
            while (!closed) {
                int n = in.read(b);
                if (n < 0) break;
                if (n > 0) queue.add(java.util.Arrays.copyOf(b, n));
            }
        } catch (IOException ignored) {
            // port closed or unplugged: reads time out from here on
        }
    }

    @Override
    public void write(byte[] data) throws IOException {
        out.write(data);
        out.flush();
    }

    @Override
    public int read(byte[] buf, double timeoutS) throws IOException {
        if (pos >= cur.length) {
            try {
                byte[] n = queue.poll((long) (timeoutS * 1e6), TimeUnit.MICROSECONDS);
                if (n == null) return 0;
                cur = n;
                pos = 0;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return 0;
            }
        }
        int n = Math.min(buf.length, cur.length - pos);
        System.arraycopy(cur, pos, buf, 0, n);
        pos += n;
        return n;
    }

    @Override
    public void close() throws IOException {
        closed = true;
        try {
            out.close();
        } finally {
            in.close();
        }
    }
}
