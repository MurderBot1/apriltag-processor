"""SimTransport: the real firmware core (native build) behind a fake FPGA and fake flash, so the full stack runs without hardware."""
import json
import os

from . import simfw
from .transport import Transport

RESULTS_JSON = os.path.join(simfw.ROOT, 'results', 'rtl_chain_results.json')


def load_rtl_frames(names=None, path=RESULTS_JSON):
    """RTL-simulation tag estimates per dataset image -> list of frame dicts {name, tags: [(id, corners, ham)]}."""
    with open(path) as f:
        data = json.load(f)
    def frame(name):
        return {'name': name, 'tags': [(t['id'], t['corners'], t.get('ham', 0)) for t in data[name]['tags']]}
    if names is None:
        return [frame(n) for n in data]
    return [frame(n) for n in names]       # in the order given, repeats allowed


class SimTransport(Transport):
    """frames: iterable of dicts {'tags': [...], 'mean': optional 0..255 image mean}.  While the host has streaming enabled every
    read() that finds no pending bytes makes the fake FPGA 'capture' the next frame and runs the firmware poll loop."""
    def __init__(self, frames=None, fw=None, flash_file=None):
        self.fw = fw or simfw.NativeFirmware()
        self.flash_file = flash_file
        if flash_file and os.path.exists(flash_file):
            with open(flash_file, 'rb') as f:
                blob = f.read()
            if len(blob) == 2 * simfw.SLOT_BYTES:
                for i in range(2):
                    self.fw.flash.slots[i][:] = blob[i * simfw.SLOT_BYTES:(i + 1) * simfw.SLOT_BYTES]
                self.fw.boot()
        self._frames = iter(frames) if frames is not None else iter(())
        self._out = bytearray()
        self.closed = False
        self.frames_fed = 0

    @property
    def fpga(self):
        return self.fw.fpga

    def feed_frames(self, frames):
        """Append more frames to the stream source."""
        import itertools
        self._frames = itertools.chain(self._frames, iter(frames))

    def capture(self, frame):
        """Fake FPGA finishes one frame, firmware processes it."""
        if 'mean' in frame:
            self.fw.fpga.frame_sum = int(frame['mean'] * simfw.FRAME_PIXELS)
        self.fw.fpga.time_us += 8333                      # one 120 fps frame period on the device clock
        self.fw.fpga.publish(frame['tags'])
        self.fw.poll()
        self._out += self.fw.take_tx()
        self.frames_fed += 1

    def write(self, data: bytes) -> None:
        if self.closed:
            raise IOError('transport closed')
        self.fw.rx(data)
        self._out += self.fw.take_tx()
        self._save()

    def read(self, max_bytes: int, timeout: float) -> bytes:
        if self.closed:
            raise IOError('transport closed')
        if not self._out and self.fw.stats()['streaming']:
            frame = next(self._frames, None)
            if frame is not None:
                self.capture(frame)
        out = bytes(self._out[:max_bytes])
        del self._out[:max_bytes]
        return out

    def reboot(self):
        """Power-cycle the MCU (flash and FPGA keep state); the host sees a silent device that re-reads its stored config."""
        self.fw.boot()
        self._out.clear()

    def _save(self):
        if self.flash_file:
            with open(self.flash_file, 'wb') as f:
                f.write(b''.join(bytes(s) for s in self.fw.flash.slots))

    def close(self):
        self.closed = True
