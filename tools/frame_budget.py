"""Frame drop model of architecture A3: how often does the RP2350 miss a frame at 120 fps, given the per-frame run time of the C tag unit?

Model (all times in ms, a frame period T = 1041 lines x 8.0 us = 8.328 ms):
  * the FPGA streams a frame packet that starts S after the sensor frame start (17-row threshold delay) and is complete R after it (the
    mask leaves at the pixel rate, then the 4 KB candidate list; measured in the RTL chain run: results/chain_packets.json);
  * the receiver (DMA) needs a free frame buffer when a packet starts; there are NBUF (2) buffers, a packet is released when the processing
    of its frame has finished; if no buffer is free the whole packet is lost (the stream stays aligned, see firmware/rp2350/hal_frame_rx.c);
  * one core processes the oldest complete packet first and is busy for d_k = the frame's run time.
The run times come from tools/m33_cycles.py (Cortex-M33 estimate; optimistic / nominal / pessimistic table).  The model is applied to a stream
made of the frames of one dataset category repeated (a camera watching a similar scene), and to the whole dataset in file order.

    py -3.12 tools/frame_budget.py [--json results/tpu_c_m33_cycles.json] [--cores 1|2] [--pose-ms X]
"""
import os, sys, json, argparse
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

T = 1041 * 0.008                 # ms per frame
S = 17 * 0.008 + 0.01            # packet start after the sensor frame start (threshold ring delay)
R = 6.73                         # packet end after the sensor frame start (tb_cam: 672,306 clocks of 832,800 per 8.328 ms frame)


def simulate(times, nbuf=2, ncores=1, nframes=None):
    """times: per-frame processing time list (cycled).  Returns (frames offered, frames lost, max latency from packet end to result in ms)."""
    nframes = nframes or max(2000, 20 * len(times))
    free_at = [0.0] * nbuf              # time at which each buffer becomes free (inf while its frame is queued / running)
    core_free = [0.0] * ncores
    lost = 0; maxlat = 0.0
    queue = []                          # (ready time, index, duration, buffer)
    done_count = 0
    # event-free formulation: frames are processed in order; frame k's buffer is claimed at its packet start
    pending = []                        # frames received but not yet processed, in order: (ready, dur, buf)
    busy_until = [0.0] * ncores
    state = [None] * nbuf               # None free, else release time (set when processing is scheduled)
    for k in range(nframes):
        start = k * T + S
        ready = k * T + R
        # schedule everything that can start before this packet starts, to know which buffers are free at `start`
        _advance(pending, busy_until, state, start)
        buf = next((b for b in range(nbuf) if state[b] is None), None)
        if buf is None:
            lost += 1
            continue
        state[buf] = float('inf')
        pending.append((ready, times[k % len(times)], buf))
        _advance(pending, busy_until, state, ready)
    _advance(pending, busy_until, state, float('inf'))
    return nframes, lost


def _advance(pending, busy_until, state, now):
    """start queued frames on cores that become free no later than `now`; buffers are released when their processing ends (<= now)"""
    while pending:
        ready, dur, buf = pending[0]
        c = min(range(len(busy_until)), key=lambda i: busy_until[i])
        t0 = max(ready, busy_until[c])
        if t0 > now:
            break
        busy_until[c] = t0 + dur
        state[buf] = t0 + dur
        pending.pop(0)
    for b in range(len(state)):
        if state[b] is not None and state[b] != float('inf') and state[b] <= now:
            state[b] = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=os.path.join(ROOT, 'sim', 'm33_chain_O3.json'))
    ap.add_argument('--cores', type=int, default=1); ap.add_argument('--bufs', type=int, default=2)
    ap.add_argument('--pose-ms', type=float, default=0.0, help='extra per-frame time on the same core (pose solve, USB, AE)')
    a = ap.parse_args()
    d = json.load(open(a.json))
    mhz = d['mhz']
    cats = sorted({r['cat'] for r in d['rows']})
    print(f'one frame period {T:.3f} ms, {a.bufs} buffers, {a.cores} core(s), extra {a.pose_ms} ms per frame; per category the 10 frames are repeated')
    print('| category | frames | lost optimistic | lost nominal | lost pessimistic | lost (old design, TPU in the FPGA) |')
    print('|---|---|---|---|---|---|')
    tot = {m: [0, 0] for m in ('optimistic', 'nominal', 'pessimistic')}
    for c in cats + ['all']:
        rs = [r for r in d['rows'] if c == 'all' or r['cat'] == c]
        cells = []
        for m in tot:
            t = [r['cycles'][m] / (mhz * 1000.0) + a.pose_ms for r in rs]
            n, lost = simulate(t, a.bufs, a.cores)
            cells.append(f'{lost}/{n} ({100 * lost / n:.1f} %)')
            if c == 'all': tot[m] = [n, lost]
        print(f'| {c} | {len(rs)} | ' + ' | '.join(cells) + ' | |')


if __name__ == '__main__':
    main()
