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
    ap.add_argument('--tpu', default=os.path.join(ROOT, 'results', 'tpu_c_m33_cycles.json'), help='output of tools/m33_cycles.py --json')
    ap.add_argument('--pose', default=os.path.join(ROOT, 'results', 'pose_m33_cycles.json'), help='output of tools/m33_pose_cycles.py --json')
    ap.add_argument('--bufs', type=int, default=2)
    a = ap.parse_args()
    d = json.load(open(a.tpu)); mhz = d['mhz']
    pose = json.load(open(a.pose)) if os.path.exists(a.pose) else {}
    pose_ms = {lab: {r['name']: r['ms'] for r in rows} for lab, rows in pose.items()}
    cats = sorted({r['cat'] for r in d['rows']}) + ['all']
    print(f'frame period {T:.3f} ms, {a.bufs} frame buffers; per category the 10 frames repeat; "lost" = frames with no free buffer when their packet starts')
    print('TPU run times: tools/m33_cycles.py (C tag unit, 150 MHz, -O3); pose: tools/m33_pose_cycles.py (float = FPU single precision, double = software doubles)')
    print()
    scen = [('TPU only, 1 core', None, 1)]
    for lab in pose:
        scen += [(f'TPU + pose ({lab}), 1 core', lab, 1), (f'TPU + pose ({lab}), 2 cores (alternate frames)', lab, 2)]
    for model in ('nominal', 'pessimistic'):
        print(f'### cycle model: {model}')
        print('| category | frames | ' + ' | '.join(n for n, _, _ in scen) + ' |')
        print('|---|---|' + '---|' * len(scen))
        for c in cats:
            rs = [r for r in d['rows'] if c == 'all' or r['cat'] == c]
            cells = []
            for _, lab, cores in scen:
                t = [r['cycles'][model] / (mhz * 1000.0) + (pose_ms[lab][r['name']][model] if lab and r['tags'] else 0.0) for r in rs]
                n, lost = simulate(t, a.bufs, cores)
                cells.append(f'{lost}/{n} ({100 * lost / n:.1f} %)')
            print(f'| {c} | {len(rs)} | ' + ' | '.join(cells) + ' |')
        print()
        tt = [r['cycles'][model] / (mhz * 1000.0) for r in d['rows']]
        print(f'TPU per frame {model}: median {np.median(tt):.2f} ms, max {max(tt):.2f} ms')
        for lab in pose:
            pp = [pose_ms[lab][r['name']][model] for r in d['rows'] if r['tags']]
            print(f'pose ({lab}) {model}: median {np.median(pp):.2f} ms, max {max(pp):.2f} ms')
        print()


if __name__ == '__main__':
    main()
