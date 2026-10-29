package com.apriltag.camera;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/**
 * Device -> host clock mapping from GET_TIME round trips. Keeps (host midpoint, device time, rtt) samples; the min-RTT sample
 * gives the offset (error <= rtt/2). With fit and >= 3 low-RTT samples a linear fit also estimates the relative skew.
 */
public class ClockSync {
    private record Sample(double hostMid, double devS, double rtt) {}

    private final Deque<Sample> samples = new ArrayDeque<>();
    private final int maxSamples;
    private final boolean fit;
    private double[] model;     // {devRef (s), hostRef (s), slope (host s per device s)}

    public ClockSync() {
        this(64, true);
    }

    public ClockSync(int maxSamples, boolean fit) {
        this.maxSamples = maxSamples;
        this.fit = fit;
    }

    /** t0/t1: host clock seconds before send and after receive of a GET_TIME exchange. */
    public synchronized void addSample(double t0, double t1, long deviceUs, long tickHz) {
        if (t1 < t0) throw new IllegalArgumentException("t1 < t0");
        if (samples.size() == maxSamples) samples.removeFirst();
        samples.addLast(new Sample((t0 + t1) / 2, deviceUs / (double) tickHz, t1 - t0));
        model = null;
    }

    /** Runs n GET_TIME round trips on the camera. */
    public ClockSync sample(Camera cam, int n) throws IOException {
        for (int i = 0; i < n; i++) {
            Camera.TimeSample s = cam.getTimeSample();
            addSample(s.t0(), s.t1(), s.time().nowUs(), s.time().tickHz());
        }
        return this;
    }

    public synchronized double bestRtt() {
        double m = Double.NaN;
        for (Sample s : samples) if (Double.isNaN(m) || s.rtt < m) m = s.rtt;
        return m;
    }

    private double[] build() {
        if (model != null) return model;
        if (samples.isEmpty()) throw new IllegalStateException("no clock samples");
        Sample best = null;
        for (Sample s : samples) if (best == null || s.rtt < best.rtt) best = s;
        double[] m = {best.devS, best.hostMid, 1.0};
        if (fit && samples.size() >= 3) {
            List<Sample> use = new ArrayList<>();
            for (Sample s : samples) if (s.rtt <= 2 * best.rtt + 1e-9) use.add(s);
            if (use.size() >= 3) {
                double xm = 0, ym = 0;
                for (Sample s : use) { xm += s.devS; ym += s.hostMid; }
                xm /= use.size();
                ym /= use.size();
                double sxx = 0, sxy = 0;
                for (Sample s : use) { sxx += (s.devS - xm) * (s.devS - xm); sxy += (s.devS - xm) * (s.hostMid - ym); }
                if (sxx > 0) m = new double[] {xm, ym, sxy / sxx};
            }
        }
        return model = m;
    }

    /** host - device seconds at the reference sample. */
    public synchronized double offsetS() {
        double[] m = build();
        return m[1] - m[0];
    }

    /** Host seconds per device second minus one, in ppm. */
    public synchronized double skewPpm() {
        return (build()[2] - 1) * 1e6;
    }

    /** Device ticks -> host seconds in the Camera clock domain (System.nanoTime based by default). */
    public synchronized double toHost(long deviceUs, long tickHz) {
        double[] m = build();
        return m[1] + (deviceUs / (double) tickHz - m[0]) * m[2];
    }

    public synchronized double toDeviceUs(double hostS, long tickHz) {
        double[] m = build();
        return (m[0] + (hostS - m[1]) / m[2]) * tickHz;
    }

    public double poseHostTime(Protocol.Pose pose) {
        return toHost(pose.timestampUs(), 1_000_000);
    }
}
