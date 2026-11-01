"""Frame drop model of architecture A3: how often does the RP2350 miss a frame at 120 fps, given the per-frame run time of the C tag unit?

Model (all times in ms, a frame period T = 1041 lines x 8.0 us = 8.328 ms):
  * the FPGA streams a frame packet that starts S after the sensor frame start (17-row threshold delay) and is complete R after it (the
    mask leaves at the pixel rate, then the 4 KB candidate list; measured in the RTL chain run: results/chain_packets.json);
  * the receiver (DMA) needs a free frame buffer when a packet starts; there are NBUF (2) buffers, a packet is released when the processing
    of its frame has finished; if no buffer is free the whole packet is lost (the stream stays aligned, see firmware/rp2350/hal_frame_rx.c);
  * one core processes the oldest complete packet first and is busy for d_k = the frame's run time.
The run times come from tools/m33_cycles.py (Cortex-M33 estimate; optimistic / nominal / pessimistic table).  The model is applied to a stream
made of the frames of one dataset category repeated (a camera watching a similar scene), and to the whole dataset in file order.

Scheduling designs compared (`--bufs N`, `--design`, default prints all designs in results/frame_budget.md):
  single        one core runs tag unit then pose; the frame buffer is held until both are done (the firmware as first built, 2 buffers)
  single_early  same core order, but the buffer is released as soon as the tag unit has copied its tags out (the pose solve needs no mask)
  alt           two cores, frames alternate between them, each core runs tag unit + pose on its own frame (buffer held until done)
  pipe          core 0 runs the tag unit and releases the buffer, core 1 runs the pose solve (+ USB) on the tags: a two-stage pipeline

    py -3.12 tools/frame_budget.py [--bufs N] [--design single|single_early|alt|pipe] [--tpu ...] [--pose ...] [--summary]
"""
import os, sys, json, argparse
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

T = 1041 * 0.008                 # ms per frame
S = 17 * 0.008 + 0.01            # packet start after the sensor frame start (threshold ring delay)
R = 6.73                         # packet end after the sensor frame start (tb_cam: 672,306 clocks of 832,800 per 8.328 ms frame)


def simulate(times, nbuf=2, ncores=1, nframes=None, holds=None, stats=None):
    """times: per-frame core time list (cycled).  holds: per-frame time a frame buffer stays occupied after the frame starts processing
    (default = the whole core time; shorter when the buffer is released before the pose solve).
    Returns (frames offered, frames lost).  `stats` (dict, optional) gets 'max_queue' = most packets ever waiting for a core."""
    nframes = nframes or max(2000, 20 * len(times))
    pending = []                        # frames received but not yet processed, in order: (ready, dur, hold, buf)
    busy_until = [0.0] * ncores
    state = [None] * nbuf               # None free, inf while queued / running, else release time
    lost = 0
    for k in range(nframes):
        start = k * T + S
        ready = k * T + R
        _advance(pending, busy_until, state, start)
        buf = next((b for b in range(nbuf) if state[b] is None), None)
        if buf is None:
            lost += 1
            continue
        state[buf] = float('inf')
        d = times[k % len(times)]
        pending.append((ready, d, d if holds is None else holds[k % len(holds)], buf))
        if stats is not None:
            stats['max_queue'] = max(stats.get('max_queue', 0), len(pending))
        _advance(pending, busy_until, state, ready)
    _advance(pending, busy_until, state, float('inf'))
    return nframes, lost


def _advance(pending, busy_until, state, now):
    """start queued frames on cores that become free no later than `now`; buffers are released when their hold ends (<= now)"""
    while pending:
        ready, dur, hold, buf = pending[0]
        c = min(range(len(busy_until)), key=lambda i: busy_until[i])
        t0 = max(ready, busy_until[c])
        if t0 > now:
            break
        busy_until[c] = t0 + dur
        state[buf] = t0 + hold
        pending.pop(0)
    for b in range(len(state)):
        if state[b] is not None and state[b] != float('inf') and state[b] <= now:
            state[b] = None


DESIGNS = [('single', 'one core: tag unit + pose, buffer held until both done'),
           ('single_early', 'one core: tag unit + pose, buffer released after the tag unit'),
           ('alt', 'two cores alternating frames (tag unit + pose each)'),
           ('pipe', 'core 0 tag unit, core 1 pose (two-stage pipeline)')]


def run_design(design, tpu, pose, nbuf):
    """tpu, pose: per-frame times (ms, pose 0 for a frame without tags).  Returns (offered, lost, max packets waiting)."""
    st = {}
    if design == 'single':
        n, lost = simulate([a + p for a, p in zip(tpu, pose)], nbuf, 1, stats=st)
    elif design == 'single_early':
        n, lost = simulate([a + p for a, p in zip(tpu, pose)], nbuf, 1, holds=list(tpu), stats=st)
    elif design == 'alt':
        n, lost = simulate([a + p for a, p in zip(tpu, pose)], nbuf, 2, stats=st)
    elif design == 'pipe':
        n, lost = simulate(list(tpu), nbuf, 1, stats=st)
    else:
        raise ValueError(design)
    return n, lost, st.get('max_queue', 0)


def pipe_pose_lag(tpu, pose):
    """Pose stage of the pipe design (core 1): worst delay between the tag unit result and the pose result, ms, over the repeated stream.
    The stream is not lossy here (the pose stage only needs the 40-byte-per-tag list, so a deeper queue costs bytes, not frame buffers)."""
    t_core0 = 0.0; t_core1 = 0.0; worst = 0.0
    for k in range(max(2000, 20 * len(tpu))):
        ready = k * T + R
        t0 = max(ready, t_core0); t_core0 = t0 + tpu[k % len(tpu)]
        t1 = max(t_core0, t_core1); t_core1 = t1 + pose[k % len(pose)]
        worst = max(worst, t_core1 - t_core0)
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tpu', default=os.path.join(ROOT, 'results', 'tpu_c_m33_cycles.json'), help='output of tools/m33_cycles.py --json')
    ap.add_argument('--pose', default=os.path.join(ROOT, 'results', 'pose_m33_cycles.json'), help='output of tools/m33_pose_cycles.py --json')
    ap.add_argument('--bufs', type=int, nargs='+', default=[2, 3], help='numbers of frame buffers to evaluate')
    ap.add_argument('--design', nargs='+', default=[d for d, _ in DESIGNS], choices=[d for d, _ in DESIGNS])
    a = ap.parse_args()
    d = json.load(open(a.tpu)); mhz = d['mhz']
    pose = json.load(open(a.pose)) if os.path.exists(a.pose) else {}
    pose_ms = {lab: {r['name']: r['ms'] for r in rows} for lab, rows in pose.items()}
    cats = sorted({r['cat'] for r in d['rows']}) + ['all']
    print(f'frame period {T:.3f} ms; per category the 10 frames repeat (2000 frames); "lost" = frames with no free buffer when their packet starts.')
    print('TPU run times: tools/m33_cycles.py (C tag unit, 150 MHz, -O3); pose: tools/m33_pose_cycles.py (float = FPU single precision, double = software doubles).')
    print('ESTIMATES from an emulated Cortex-M33, not measurements on the RP2350.')
    print()
    for lab, text in DESIGNS:
        if lab in a.design:
            print(f'* `{lab}`: {text}')
    print()
    for nbuf in a.bufs:
        print(f'## {nbuf} frame buffers ({nbuf} x {AT_PKT_BYTES // 1024} KB = {nbuf * AT_PKT_BYTES // 1024} KB of the 520 KB SRAM)')
        print()
        for model in ('nominal', 'pessimistic'):
            for plab in pose:
                print(f'### {nbuf} buffers, cycle model {model}, pose = {plab}')
                print('| category | frames | ' + ' | '.join(a.design) + ' |')
                print('|---|---|' + '---|' * len(a.design))
                for c in cats:
                    rs = [r for r in d['rows'] if c == 'all' or r['cat'] == c]
                    tpu = [r['cycles'][model] / (mhz * 1000.0) for r in rs]
                    pz = [pose_ms[plab][r['name']][model] if r['tags'] else 0.0 for r in rs]
                    cells = []
                    for dz in a.design:
                        n, lost, q = run_design(dz, tpu, pz, nbuf)
                        cells.append(f'{lost}/{n} ({100 * lost / n:.1f} %)')
                    print(f'| {c} | {len(rs)} | ' + ' | '.join(cells) + ' |')
                print()
        print()
    for model in ('nominal', 'pessimistic'):
        tt = [r['cycles'][model] / (mhz * 1000.0) for r in d['rows']]
        print(f'TPU per frame {model}: median {np.median(tt):.2f} ms, max {max(tt):.2f} ms')
        for lab in pose:
            pp = [pose_ms[lab][r['name']][model] for r in d['rows'] if r['tags']]
            print(f'pose ({lab}) {model}: median {np.median(pp):.2f} ms, max {max(pp):.2f} ms')
            rs = d['rows']
            tpu = [r['cycles'][model] / (mhz * 1000.0) for r in rs]
            pz = [pose_ms[lab][r['name']][model] if r['tags'] else 0.0 for r in rs]
            print(f'  pipe design, pose stage on core 1 ({lab}, {model}): worst delay tag result -> pose result {pipe_pose_lag(tpu, pz):.2f} ms')
    print()
    print('Most packets waiting for the core (queue depth, all 100 frames, nominal, float pose); a depth of N needs N + 1 buffers (one being filled):')
    tpu = [r['cycles']['nominal'] / (mhz * 1000.0) for r in d['rows']]
    lab = next(iter(pose)) if pose else None
    pz = [pose_ms[lab][r['name']]['nominal'] if r['tags'] else 0.0 for r in d['rows']] if lab else [0.0] * len(tpu)
    for dz in a.design:
        print(f'* {dz} with 8 buffers: {run_design(dz, tpu, pz, 8)[2]}')


AT_PKT_BYTES = 4 * (4 + 32000 + 4 + 1024)


if __name__ == '__main__':
    main()
