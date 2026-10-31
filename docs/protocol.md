# AprilTag camera USB protocol

Transport: USB-C CDC serial (virtual COM port; baud rate is ignored). The link is a plain byte stream, so every message is
framed. Source of truth: `firmware/core/atproto.[ch]`, `firmware/core/atapp.c`; host implementation
`host/apriltag_cam/protocol.py`. `tests/test_fw_proto.py::test_doc_*` checks the tables below against `atproto.h`.

All multi-byte integers and floats are **little endian**; floats are IEEE-754 binary32.

## 1. Framing

```
frame (on the wire) = COBS( type[1] | body[0..256] | crc16[2] ) | 0x00
```

* `type`: message id (tables below).
* `crc16`: CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, xorout 0) over `type | body`, stored low byte first.
  Check value: `crc16("123456789") = 0x29B1`.
* COBS: standard Consistent Overhead Byte Stuffing (a code byte 0xFF means 254 data bytes follow and no implicit zero).
  The encoded data contains no 0x00 byte, so `0x00` is an unambiguous frame delimiter and resynchronisation point.
* Maximum body 256 bytes (`AT_MAX_BODY`); the receiver buffers 264 bytes of encoded data (`AT_MAX_FRAME`).
* Receiver: bytes are collected until 0x00. An empty frame (consecutive 0x00) is ignored. A frame that overflows the buffer,
  fails COBS decoding, is shorter than 3 decoded bytes, or fails the CRC is dropped (and counted) without any reply.
  Garbage before a frame is harmless if a 0x00 separates it from the frame; a host should therefore send a lone `0x00`
  before the first command after (re)opening the port.
* Request/response: the device answers every command with exactly one frame (ACK, NAK or a typed response). Commands are
  idempotent, so a host may retry on timeout. While streaming is enabled, unsolicited `POSE` frames are interleaved.

## 2. Message ids

Host to device:

| id   | name          | body (bytes) | response |
|------|---------------|--------------|----------|
| 0x01 | PING          | token, 4 (shorter allowed) | PONG |
| 0x02 | SET_CALIB     | 36           | ACK |
| 0x03 | CLEAR_MAP     | 0            | ACK |
| 0x04 | ADD_TAG       | 34           | ACK |
| 0x05 | COMMIT        | 0            | ACK |
| 0x06 | GET_CONFIG    | 0            | CONFIG |
| 0x07 | STREAM        | 3            | ACK |
| 0x08 | SET_SENSOR    | 3            | ACK |
| 0x09 | GET_STATUS    | 0            | STATUS |
| 0x0A | SET_TRACK     | 4            | ACK |
| 0x0B | GET_POSE      | 0            | POSE or NAK(NO_POSE) |
| 0x0C | GET_TAG       | 2            | TAG |
| 0x0D | GET_TAGS_RAW  | 0            | TAGS |
| 0x0E | SET_AE        | 1            | ACK |
| 0x0F | GET_TIME      | 0            | TIME |

Device to host:

| id   | name    | body (bytes) |
|------|---------|--------------|
| 0x80 | ACK     | 1 |
| 0x81 | PONG    | 12 |
| 0x82 | POSE    | 52 |
| 0x83 | TAGS    | 5 + 35 n (n <= 7) |
| 0x86 | CONFIG  | 40 |
| 0x87 | TAG     | 36 |
| 0x89 | STATUS  | 48 |
| 0x8A | TIME    | 20 |
| 0xFF | NAK     | 2 |

Error codes (second byte of NAK):

| code | name    | meaning |
|------|---------|---------|
| 1 | BAD_LEN | body length is not the one the command requires |
| 2 | FULL    | tag map holds 64 tags and the id is new |
| 3 | FLASH   | flash erase / program / verify failed (COMMIT), or the sensor I2C bridge rejected a write (SET_SENSOR) |
| 4 | UNKNOWN | unknown command id |
| 5 | NO_POSE | GET_POSE before any pose has been solved |
| 6 | RANGE   | value out of range (see command) |

## 3. Commands

### 0x01 PING -> 0x81 PONG
Request: `token[4]` (anything shorter than 4 bytes is answered with a zero token).
PONG: `token[4] | fw_version u32 (0x00010000 = 1.0.0) | fpga_id u32 (0x41544731 "ATG1" when the FPGA is configured and alive, else 0)`.

### 0x02 SET_CALIB (RAM only, until COMMIT)
`fx f32 | fy f32 | cx f32 | cy f32 | k1 f32 | k2 f32 | p1 f32 | p2 f32 | k3 f32` (OpenCV model, pixels; pixel centre of the top-left
pixel is (0,0)). NAK RANGE if `fx <= 1`, `fy <= 1` or either is NaN.

### 0x03 CLEAR_MAP
Empties the field map (RAM). Body ignored.

### 0x04 ADD_TAG
`id u16 | size f32 (edge of the black square, m) | pos x,y,z f32 (tag centre in world, m) | quat w,x,y,z f32 (tag->world)`.
Tag frame: x right, y up, z out of the printed face; world is Z up. Adding an existing id replaces it. NAK FULL when 64 tags are stored
and the id is new.

### 0x05 COMMIT
Writes calibration + map to flash (alternating slots, see section 6) and reads it back. ACK on success, NAK FLASH otherwise
(the previous stored configuration is untouched). Takes up to ~100 ms (flash erase); hosts should allow >= 3 s.

### 0x06 GET_CONFIG -> CONFIG
`fx fy cx cy k1 k2 p1 p2 k3 (9 x f32) | ntags u16 | reserved u16 (0)`.

### 0x0C GET_TAG -> TAG
Request `index u16` (0 .. ntags-1, else NAK RANGE). TAG: `id u16 | pad u16 (0) | size f32 | pos 3 x f32 | quat w,x,y,z 4 x f32`
(quaternion is re-derived from the stored rotation, so it can differ from the sent one by float rounding and overall sign).

### 0x07 STREAM
`enable u8 | divider u16`. When enabled the device sends one POSE frame for every `divider`-th successfully solved FPGA frame
(`divider` 0 is treated as 1). Disable with `enable = 0`.

### 0x08 SET_SENSOR
`exposure u16 (sensor lines, 1..800) | gain u8 (register value, 0x10 = 1x, >= 0x10)`. Writes OV9281 registers 0x3500..0x3502
(exposure << 4), 0x3509 (gain) through the FPGA I2C bridge with group hold. **Disables auto exposure.** NAK RANGE when out of range.

### 0x0E SET_AE
`enable u8`. 1 re-enables auto exposure (starting from the current exposure/gain), 0 disables it. Auto exposure is on after boot:
the target is mean brightness 110 (0..255, from FPGA register FRAME_SUM / 1,024,000), deadband +-12, exposure preferred up to 400
lines then gain up to 0xFF, at most 4x change per step, one frame skipped after every change.

### 0x09 GET_STATUS -> STATUS (48 bytes)

| offset | type | field |
|--------|------|-------|
| 0  | u32 | FPGA STATUS register: `frames_sent[31:16] candidates[15:8] init_done[3] stream_busy[2] 0[1] any_frame[0]` (architecture A3: `frames_sent` counts frame packets streamed to the MCU, `candidates` is the count of the last packet; the bits keep their positions from the old design, where bit 2 was `tpu_busy`) |
| 4  | u32 | FPGA CCL register (0x28): `max_row_clocks[31:16] flags[11:8] candidates[7:0]`. The flags are **diagnostics of a degraded frame, never a rejection**: bit 8 a row was dropped (labeller too slow for a very busy row), bit 9 a row had more than 256 runs (extra runs ignored), bit 10 the 1024-entry label table was full (the affected runs stayed background), bit 11 more than 64 candidates were found (only the 64 largest by area are kept). The frame is processed and its tags reported in every case; `candidates` is the number handed to the tag unit (0 is valid). |
| 8  | u32 | frames dropped: FPGA register 0x30 (sensor frames not accepted) + packets the MCU could not receive (no free frame buffer, resync) |
| 12 | u32 | frames total (FPGA register 0x34: sensor frames seen) |
| 16 | u32 | frames processed (packets run through the tag unit on the MCU) |
| 20 | u32 | pose solutions computed |
| 24 | u32 | solver failures (no known tag / degenerate / no convergence) |
| 28 | u32 | rejected frame packets (malformed, or flagged by the FPGA as damaged: sensor CRC / line-count error, FIFO overflow, short mask, labeller timeout). Legacy name `torn_reads`; there is no result bank to tear any more |
| 32 | u32 | frame id of the last processed result |
| 36 | u16 | tags in the map |
| 38 | u8  | last pose valid |
| 39 | u8  | streaming enabled |
| 40 | u16 | current exposure (lines) |
| 42 | u8  | current gain register |
| 43 | u8  | auto exposure enabled |
| 44 | u16 | last mean brightness x 256 |
| 46 | u16 | reserved (0) |

### 0x0A SET_TRACK
`diff u8 | abs_black u8 | mindim u8 | maxham u8 (low 6 bits)`, written to the FPGA THRESH register (0x0C):
local contrast threshold, absolute black level, minimum tag dimension in pixels, maximum accepted Hamming distance. The first three are used by
the FPGA; `maxham` is kept by the MCU (the tag unit runs there) and stored in the FPGA register for read-back only.
Reset values 24, 64, 10, 2.

### 0x0B GET_POSE -> POSE
Latest solved pose. NAK NO_POSE if none yet.

POSE (52 bytes), also the unsolicited streaming message:

| offset | type | field |
|--------|------|-------|
| 0  | u32 | frame id (FPGA packet sequence number of the source frame) |
| 4  | u32 | processing time on the MCU, microseconds: tag unit + pose solver |
| 8  | u8  | tags used by the solution |
| 9  | u8  | flags: 1 ambiguous (planar ambiguity unresolved), 2 outlier tag dropped, 4 single tag |
| 10 | u16 | tag observations in the frame (before filtering) |
| 12 | 3 x f32 | position x, y, z (m), camera to world: `p_w = R q + t` |
| 24 | 4 x f32 | quaternion w, x, y, z of R |
| 40 | f32 | reprojection RMS error (pixels) |
| 44 | u64 | capture timestamp: device clock (microseconds) at the start of the source frame (see GET_TIME) |

Camera frame: OpenCV (x right, y down, z forward). World Z up.

### 0x0F GET_TIME -> TIME
Device clock. The FPGA runs a free-running 64-bit counter at `tick_hz` = 1,000,000 Hz (1 us per tick) from FPGA reset; it never stops and
never wraps in practice (584,000 years). Every frame start (CSI-2 frame-start packet) latches the counter, and that value is the frame's
capture timestamp (POSE offset 44).

TIME (20 bytes): `now_us u64 | frame_us u64 | tick_hz u32`. `now_us` is the counter when the MCU served the request, `frame_us` is the
timestamp of the newest frame whose result has been processed (0 before the first), `tick_hz` is 1000000 (hosts must use it instead of
assuming). Host-side offset estimation: take `t0` before send and `t1` after the response; device time `now_us` corresponds to host
`(t0 + t1) / 2` to within half the round trip.

### 0x0D GET_TAGS_RAW -> TAGS
`frame_id u32 | count u8 | count x { id u16 | hamming u8 | 4 corners (TL, TR, BR, BL) x (x f32, y f32) }` (35 bytes per tag). At most 7 tags fit
in the 256-byte body; the first 7 observations are reported.

## 4. Streaming

After `STREAM(1, d)` the device emits `POSE` frames without request. Command responses are interleaved with them; a host must
match responses by type (and the echoed command id for ACK/NAK) and queue POSE frames. Disable on exit.

## 5. FPGA SPI map used by the MCU (for reference)

SPI mode 0, <= 12 MHz. Read: `0x03 a2 a1 a0 dummy d0 d1 ...`; write: `0x02 a2 a1 a0 w0[7:0] w0[15:8] ...` (little-endian words).

| address | register |
|---------|----------|
| 0x000000 | ID (0x41544731) |
| 0x000008 | CTRL |
| 0x00000C | THRESH |
| 0x000018 | STATUS |
| 0x00001C | FRAME_ID |
| 0x000040 / 0x000044 | I2C bridge command / data |
| 0x000064 / 0x000068 | TIME_LO / TIME_HI (reading LO latches HI, so the pair is coherent) |
| 0x000060 | FRAME_SUM (sum of all pixels of the last frame) |
| 0x00002C | streamer status: `fifo_overflows[31:16] aborted_packets[15:0]` |

The frames themselves (binary mask + candidate list) do not travel over SPI: the FPGA streams them on an 8-bit strobed bus into the RP2350 (PIO + DMA),
see `docs/fpga.md`. The tag decoder runs on the MCU (`firmware/core/attpu.c`) and produces the same records the old FPGA result RAM held: id, hamming
distance, rotation, four corners as signed Q16.16 (x, y) TL,TR,BR,BL. The sensor frame timestamp comes in the packet header (no FT0/FT1 registers any more).
## 6. Flash storage

Two 4 KB slots at the end of flash, written alternately (slot = seq & 1); each commit erases and programs only the slot that does not
hold the newest valid configuration, then reads it back. Slot image:

`magic u32 0x31465441 ("ATF1") | seq u32 | ntags u16 | reserved u16 | 9 x f32 calibration | ntags x { id u16 | pad u16 | size f32 | pos 3 x f32 | quat 4 x f32 } | crc16 u16`

(CRC-16/CCITT-FALSE over everything before it.) At boot the valid slot (magic, ntags <= 64, CRC) with the highest `seq` is loaded; if none is
valid the defaults (fx = fy = 640, cx = 639.5, cy = 399.5, no distortion, empty map) are used. A power loss at any point of a commit leaves
the previous configuration loadable (`tests/test_fw_storage.py` cuts power after every single byte operation).
