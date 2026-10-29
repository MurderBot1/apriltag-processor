#!/usr/bin/env python3
"""atcam - command line tool for the AprilTag pose camera.

  atcam.py --port COM5 configure --map config/tag_map.json --calib config/camera_calibration.json
  atcam.py --port COM5 stream --count 100
  atcam.py --port COM5 status
  atcam.py --sim --sim-state sim_flash.bin configure ...      (no hardware: native firmware + fake FPGA)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apriltag_cam import Camera, CameraError, SimTransport, load_json, load_rtl_frames   # noqa: E402


def build_parser():
    p = argparse.ArgumentParser(prog='atcam', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--port', help='serial port (e.g. COM5 or /dev/ttyACM0)')
    p.add_argument('--sim', action='store_true', help='use the simulated camera (native firmware + fake FPGA/flash)')
    p.add_argument('--sim-state', help='file that persists the simulated flash between invocations')
    p.add_argument('--sim-images', type=lambda s: s.split(','), help='comma separated dataset image names fed to the simulated FPGA (default: all)')
    p.add_argument('--timeout', type=float, default=1.0)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('ping')
    c = sub.add_parser('configure', help='send calibration + tag map and commit them to flash')
    c.add_argument('--map', required=True); c.add_argument('--calib', required=True)
    c.add_argument('--no-commit', action='store_true')
    s = sub.add_parser('stream', help='print poses')
    s.add_argument('--divider', type=int, default=1); s.add_argument('--count', type=int); s.add_argument('--json', action='store_true')
    sub.add_parser('status')
    sub.add_parser('config', help='print the configuration stored on the device')
    sub.add_parser('pose', help='print the latest pose')
    e = sub.add_parser('exposure', help='manual exposure/gain (disables AE)')
    e.add_argument('exposure', type=int); e.add_argument('gain', type=lambda x: int(x, 0), nargs='?', default=0x10)
    a = sub.add_parser('ae', help='enable/disable auto exposure'); a.add_argument('state', choices=['on', 'off'])
    return p


def open_camera(args):
    if args.sim:
        frames = load_rtl_frames(args.sim_images) if args.sim_images is not None or args.cmd == 'stream' else []
        return Camera(SimTransport(frames, flash_file=args.sim_state), timeout=args.timeout)
    if not args.port:
        raise SystemExit('error: --port or --sim required')
    return Camera.open_serial(args.port, timeout=args.timeout)


def fmt_pose(p):
    return 'frame %6d  pos [% .4f % .4f % .4f] m  q [% .4f % .4f % .4f % .4f]  rms %.3f px  tags %d  flags %d  %d us' % (
        p.frame_id, *p.position, *p.quaternion, p.rms_px, p.ntags, p.flags, p.processing_us)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open_camera(args) as cam:
            if args.cmd == 'ping':
                r = cam.ping()
                print('firmware 0x%08X  fpga id 0x%08X  rtt %.1f ms' % (r['firmware_version'], r['fpga_id'], r['rtt_s'] * 1e3))
            elif args.cmd == 'configure':
                cam.set_calibration(load_json(args.calib))
                n = cam.set_field(load_json(args.map))
                if not args.no_commit:
                    cam.commit()
                print('configured %d tags%s' % (n, '' if args.no_commit else ' and committed to flash'))
            elif args.cmd == 'stream':
                for pose in cam.stream(args.divider, max_frames=args.count, on_timeout='stop' if args.sim else 'raise'):
                    print(json.dumps(pose.__dict__) if args.json else fmt_pose(pose))
            elif args.cmd == 'status':
                for k, v in cam.get_status().__dict__.items():
                    print('%-18s %s' % (k, hex(v) if k == 'fpga_status' else v))
            elif args.cmd == 'config':
                print(json.dumps(cam.get_config(), indent=1))
            elif args.cmd == 'pose':
                print(fmt_pose(cam.get_pose()))
            elif args.cmd == 'exposure':
                cam.set_exposure_gain(args.exposure, args.gain); print('ok (auto exposure disabled)')
            elif args.cmd == 'ae':
                cam.set_ae(args.state == 'on'); print('ok')
    except CameraError as e:
        print('error:', e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
