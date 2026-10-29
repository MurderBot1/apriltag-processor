"""Regenerates golden_frames.json from the reference implementation host/apriltag_cam/protocol.py."""
import json, os, struct, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, '..', '..', 'host'))
from apriltag_cam import protocol as P

pose = struct.pack('<IIBBH', 1234, 777, 2, 1, 5) + struct.pack('<8f', 1.5, -2.25, 0.5, 1.0, 0.0, 0.0, 0.0, 0.25) \
    + struct.pack('<Q', 0x0000_0123_4567_89AB)
time_ = struct.pack('<QQI', 5_000_000_000, 4_999_000_000, 1_000_000)
status = struct.pack('<9IHBB', 0x00050A0D, 1, 2, 300, 298, 290, 8, 1, 4242, 3, 1, 1) + struct.pack('<HBBHH', 400, 0x20, 1, 110 * 256, 0)
tags = struct.pack('<IB', 99, 1) + struct.pack('<HB', 7, 1) + struct.pack('<8f', 1, 2, 3, 4, 5, 6, 7, 8)
cases = [
    ('ping', P.CMD_PING, b'ping'),
    ('get_time', 0x0F, b''),
    ('stream_on_div3', P.CMD_STREAM, struct.pack('<BH', 1, 3)),
    ('set_calib', P.CMD_SET_CALIB, P.encode_calib(640, 641, 639.5, 399.5, 0.1, -0.2, 0.001, 0.002, 0.03)),
    ('add_tag', P.CMD_ADD_TAG, P.encode_tag(12, 0.165, (1, 2, 3), (1, 0, 0, 0))),
    ('pose', P.RSP_POSE, pose),
    ('time', 0x8A, time_),
    ('status', P.RSP_STATUS, status),
    ('tags', P.RSP_TAGS, tags),
    ('nak_no_pose', P.RSP_NAK, bytes([0x0B, 5])),
    ('ack', P.RSP_ACK, bytes([0x03])),
    ('run254', P.RSP_TAGS, bytes(range(1, 255))),          # 254 non-zero bytes after the type byte -> 0xFF code block
    ('zeros', P.RSP_TAGS, bytes(40)),
]
out = {'crc16_check': {'input': '123456789', 'value': P.crc16(b'123456789')},
       'frames': [dict(name=n, type=t, body=b.hex(), frame=P.encode_frame(t, b).hex()) for n, t, b in cases]}
with open(os.path.join(here, 'golden_frames.json'), 'w') as f:
    json.dump(out, f, indent=1)
print(len(cases), 'frames', hex(out['crc16_check']['value']))
# line-oriented copy for libraries without a JSON parser: "name type body_hex frame_hex" ('-' = empty body)
with open(os.path.join(here, 'golden_frames.txt'), 'w') as f:
    for c in out['frames']:
        f.write('%s %d %s %s\n' % (c['name'], c['type'], c['body'] or '-', c['frame']))
