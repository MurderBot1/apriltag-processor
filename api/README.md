# AprilTag camera client libraries

Four self-contained clients for the USB CDC protocol in `docs/protocol.md` (COBS + CRC-16/CCITT-FALSE framing). All have the same
shape: a `Transport` (serial or in-memory loopback), a `Camera` with every command, streamed-pose handling, and a `ClockSync` that maps
the device clock (`Pose.timestamp_us`, `GET_TIME`) to host monotonic time.

| | path | deps | tests |
|---|---|---|---|
| Python | `python/apriltag_camera` | none (`pyserial` for serial) | `cd python && python -m unittest discover -s tests` |
| Rust | `rust` (+ `rust/serial` crate) | none (`serialport` only in `rust/serial`) | `cd rust && cargo test --offline` |
| Java | `java` | none (plain `java.io`; pluggable `Transport`) | `cd java && sh build.sh` (or `build.bat`) |
| C++17 | `cpp` | none (Win32 / termios) | `cd cpp && make test` (or CMake + `ctest`) |

`testdata/golden_frames.json|txt` holds frames produced by `host/apriltag_cam/protocol.py` (regenerate with `python testdata/gen_golden.py`);
every library's tests encode and decode against them.

Common behaviour: a lone `0x00` is sent when the camera object is created; a command is retried on silence (default 2 retries, 1 s
timeout; COMMIT waits >= 3 s) and then raises a timeout error; a NAK for the command raises a typed NAK error carrying the code
(`NO_POSE`, `RANGE`, ...); POSE frames arriving while a response is awaited are queued for `poll_pose` / the pose iterator.
`get_time()` returns `{now_us, frame_us, tick_hz}`. `ClockSync` takes round-trip samples (`t0`, `t1`, `now_us`), uses the device time
at the midpoint `(t0 + t1) / 2`, keeps the min-RTT sample for the offset and (optionally) fits a line through the low-RTT samples
to estimate skew. `to_host(pose.timestamp_us)` returns seconds in the Camera's host clock (monotonic).

## Python

```python
from apriltag_camera import Camera, ClockSync, NakError

with Camera.open_serial("COM5") as cam:            # needs pyserial; any Transport works: Camera(my_transport)
    print(cam.ping())
    cam.set_calibration(640, 640, 639.5, 399.5)
    cam.clear_map(); cam.add_tag(0, 0.165, (0, 0, 0), (1, 0, 0, 0)); cam.commit()
    sync = ClockSync().sample(cam, 16)
    for pose in cam.poses(divider=1, max_frames=100):    # enables streaming, disables on exit
        print(pose.position, sync.to_host(pose.timestamp_us))
    try:
        cam.get_pose()
    except NakError as e:
        print(e.code)
```

## Rust

```rust
use apriltag_camera::{Camera, ClockSync};
use apriltag_camera_serial::SerialTransport;   // crate in rust/serial; the core crate has no dependencies
use std::time::Duration;

let mut cam = Camera::new(SerialTransport::open("COM5")?)?;
let (fw, fpga, _rtt) = cam.ping()?;
let mut sync = ClockSync::default();
sync.sample(&mut cam, 16)?;
for pose in cam.poses(1, Duration::from_secs(1))?.take(100) {   // streaming stops when the iterator is dropped
    let pose = pose?;
    println!("{:?} {}", pose.position, sync.pose_host_time(&pose));
}
```

## Java

```java
import com.apriltag.camera.*;

try (Camera cam = Camera.openPort("\\\\.\\COM5")) {          // plain java.io; or new Camera(yourTransport)
    System.out.println(cam.ping());
    ClockSync sync = new ClockSync().sample(cam, 16);
    try (Camera.PoseStream s = cam.poses(1, 1.0)) {
        for (int i = 0; i < 100; i++) {
            Protocol.Pose p = s.next();
            System.out.println(sync.poseHostTime(p));
        }
    }
} catch (CameraException.Nak e) { System.out.println(e.code); }
```

Linux/macOS: put the tty in raw mode first (`stty -F /dev/ttyACM0 raw -echo`) or plug a serial library in by implementing `Transport`
(or wrapping its streams in `StreamTransport`), e.g. with jSerialComm: `new StreamTransport(port.getInputStream(), port.getOutputStream())`.

## C++

```cpp
#include "apriltag/clock.hpp"
using namespace apriltag;

Camera cam = Camera::open_serial("COM5");                    // or Camera(std::make_unique<MyTransport>())
auto info = cam.ping();
ClockSync sync;
sync.sample(cam, 16);
auto stream = cam.poses(1, 1.0);                             // RAII: streaming off on destruction
for (int i = 0; i < 100; i++) {
    Pose p = stream.next();
    double host_s = sync.pose_host_time(p);
}
try { cam.get_pose(); } catch (const NakError& e) { /* e.code */ }
```

Build: `make` in `cpp/` produces `build/libapriltag_camera.a`, or add `cpp/CMakeLists.txt` as a subdirectory and link `apriltag_camera`.

## Testing without hardware

Every language has an in-memory `LoopbackTransport(handler)`; the handler receives each written byte chunk and returns the bytes the
fake device sends back. The test suites use it for a fake device covering interleaved streaming, NAK, retries, and ClockSync with a
simulated offset and a 200 ppm skew (virtual clock, deterministic).
