# AprilTag camera housing

Two FDM parts generated from `housing.scad` (OpenSCAD 2021.01), sized from `../pcb/pcb_params.json` (run `py -3.12 gen_params.py` first; it writes `pcb_params.scad`, which `housing.scad` includes).

```
set PATH=C:\msys64\ucrt64\bin;%PATH%
openscad -D "part=\"front\"" -o output/front.stl housing.scad
openscad -D "part=\"back\""  -o output/back.stl  housing.scad
openscad -D "part=\"assembly\"" --render --imgsize 1200,900 --camera 0,0,12,60,0,35,230 -o output/assembly.png housing.scad
openscad -D "part=\"exploded\"" --render --imgsize 1200,1200 --camera 0,0,22,65,0,30,330 -o output/exploded.png housing.scad
```
Tests: `py -3.12 -m pytest tests/test_housing.py -q`.

## Design summary
* BACK shell: floor 2.4, walls 2.4, four 6 mm posts at (+-20.5, +-20.5) (4.0 mm tall) whose top faces are the PCB seating plane (0.8 mm under the 3.2 mm bottom-side parts). M2 clearance holes (2.4) with 4.4 x 1.4 head counterbores in the underside, USB-C cut-out (9.34 x 3.66, centre y = -8) in the left wall, 2.5 mm boot-button access hole at (20,4), five 1.6 x 14 vent slots under the FPGA (centre (0,-8)), inner 1.0 x 1.5 lap tongue.
* FRONT cover: 45 degree conical roof (no supports when printed rim-down), 15 mm lens bore in a 19 mm OD hood centred on the sensor axis (0, 9); the cone roof and outer shell are clipped to the walls, corner bosses with 1.8 mm self-tapping pilots that press on the PCB top, lap groove, LED well plus two 2.0 mm bores for 1.75 mm clear-filament light pipes (cut to ~4.5 mm, glue flush). The bores run straight up (+Z) through the FLAT part of the roof (outside the 18.5 mm cone start radius) so they are perpendicular to the surface they exit; the LEDs are at (-21.5, -6.5) and (-21.5, -9.5), above the USB-C receptacle (they used to be at (9, 21.5) and (12, 21.5), where the roof is the 45 degree cone).
* LED symbols: engraved 0.6 mm deep into the flat outer roof, stroke 0.8 mm, 4.4 mm envelope, upright when looking at the lens side with the USB-C at the left. PWR = IEC 5009 power symbol (ring open at the top with a vertical bar) centred at (-20.3, -2.5), directly above the PWR bore; STAT = heartbeat/pulse line centred at (-20.3, -13.5), directly below the STAT bore. The firmware blinks STAT as a heartbeat (1 Hz healthy, 5 Hz FPGA configuration failed), so a pulse line says "activity/status" in a form that needs no text and prints as one continuous 0.8 mm stroke (2 perimeters). The symbols sit beyond the bores (0.8 mm gap), outside the 18.5 mm cone start radius, 1.1 mm inside the outer wall and far from the screw bosses; the roof under them stays 1.8 mm thick. Parametric: `sym_size`, `sym_depth`, `sym_w`, `sym_gap`, `sym_dx`, modules `sym_power()` / `sym_pulse()`, positions `sym_pos(i)` derived from `led_pos` (generated from `pcb_params.json`, index 0 = PWR, 1 = STAT).
* PCB is captured: lateral 0.2 mm clearance in the cavity (+ screw shanks in the 2.2 mm holes), vertical clamp between the four post shoulders and the four front bosses; top parts (lens holder 7.4 mm) have at least 1.6 mm headroom under the cone roof, bottom parts 0.8 mm.
* Snap fits vs screws: screws chosen. The front is a rigid cone and the PCB must be clamped without play; snaps on 2.4 mm PLA walls would be reworkable only with risk of cracking and give no clamp force. The lap joint also blocks light.

## Print settings
PLA or PETG, 0.4 mm nozzle, 0.2 mm layers, 3 perimeters, 20 % gyroid, no supports, no brim needed. Black or dark-grey filament (stray light into the lens). BACK: floor down (as modelled). FRONT: rim down on the bed, hood pointing up (as in `front.stl`). The USB cut-out roof bridges 9.3 mm (acceptable); the 1.6 mm LED well bridge is tiny. Print the filament light pipes as clear 1.75 mm filament offcuts.

## Hardware
| Qty | Item |
|---|---|
| 4 | M2 x 10 pan/button head screws (see note), head <= 3.8 mm dia x <= 1.4 mm high (DIN 7985 pan is 4.0 x 1.7: too big; ISO 7380 button head 3.4 x 1.3 fits) |
| 4 (optional) | M2 knurled brass heat-set inserts, 4 mm long, 3.5 mm OD, into a 3.2 mm pilot in the front bosses; set `pilot_d = 3.2` (a 5 mm long insert does not fit the 4.0 mm pilot depth) |
| 2 | 1.75 mm clear filament, ~4.5 mm long (LED light pipes) |
Note: M2 x 8 was requested but the stack (head seat to boss) is 6.2 mm + 1.6 mm PCB, so M2 x 8 would engage only 1.8 mm in the front boss. M2 x 10 gives 3.4 mm engagement (pilot depth 4.0). Use M2 x 10.

## Assembly
1. Drop the PCB, lens side up, onto the four posts; the screws' holes must line up with the PCB mounting holes (USB-C at the left, in the cut-out).
2. Fit the lens holder (CLA021-LCP, 2 x M1.6 x 5 screws from the PCB underside) and focus the lens (CIL023, lens top allowance 22.0 mm above the PCB).
3. Insert the light pipes into the front cover bores from below (or from above after assembly).
4. Lower the FRONT cover over the lens so the tongue enters the groove.
5. Turn the housing over, drive four M2 x 10 screws up through the back posts into the front bosses (do not over-tighten; PLA).
6. Boot button: press with a 2 mm pin through the hole in the floor.

## Dimension table
| Item | mm |
|---|---|
| Outer footprint | 53.2 x 53.2, corner R3 |
| Overall height (assembled) | 30.3 (split plane at z = 8.0, back incl. tongue 9.5) |
| Cavity (lateral) | 48.4 x 48.4 (0.2 per side) |
| Wall / floor / roof (vertical) | 2.4 / 2.4 / 2.4; hood wall 2.0 |
| PCB bottom / top above outer floor | 6.4 / 8.0 |
| Floor to PCB (bottom parts 3.2 mm) | 4.0 |
| Lens aperture (bore) | 15.0 dia, axis at (0, +9) |
| Hood rim above PCB top | 22.3 (lens front allowance at 22.0) |
| Hood height above front-cover flat roof (5.0) | 17.3 |
| USB-C opening | 9.34 x 3.66, centre z = 4.8, y = -8 |
| Boot hole | 2.5 dia at (20, 4) |
| Vents | 5 slots 1.6 x 14, pitch 3.4, centred on (0,-8) |
| Screws | M2 x 10 at (+-20.5, +-20.5) |
| Holder screws | M1.6 x 5 at (+-10, 9), from the PCB underside, head allowance 3.4 x 1.3 under the board (2.7 mm to the floor) |

## Optics and lens stack (re-derived 2026-10-31)
Parts (details and sources in `docs/bom/bom.json` and `docs/bom/AUDIT.md`):
* Lens: Commonlands **CIL023-F2.2-M12B650**, EFL 2.2 mm, f/2.2, 650 nm IR-cut, -5 % TV distortion, 7.2 mm image circle, USD 39.00, 270 in stock (2026-10-31).
* Holder: Commonlands **CLA021-LCP**, 7.4 mm tall, 17 x 17 mm footprint, 20 mm hole spacing, USD 4.50, 1074 in stock (2026-10-31). Commonlands lists 6 to 9 mm tall holders for the CIL023, so 7.4 mm fits. (The earlier choice CIL018 needs a 9 to 13 mm holder; the only such holder with 20 mm spacing, CLA020-PC at 10.0 mm, is out of stock.)
* Screws: Commonlands CLA904-SCR, M1.6 x 5 thread-forming (fits 1.6 and 1.7 mm holder holes).

Sensor OV9281 1280 x 800 at 3 um pixels (active 3.84 x 2.40 mm, diagonal 4.53 mm; sensor numbers as in the BOM audit). Rectilinear HFOV = 2 atan(1.92/2.2) = 82.2 deg (VFOV 57.2 deg, diagonal 91.7 deg, half-diagonal angle 45.8 deg). The 7.2 mm image circle covers the 4.53 mm diagonal with 2.7 mm spare. With the lens distortion the real half-angles are larger: a one-point model fitted to the published "121 deg at 7.2 mm" gives roughly 84.5 deg HFOV and 47 deg half-diagonal (an estimate, not a datasheet value). The housing therefore uses a 50 deg half-angle for the cone check. Nominal fx = 2.2 mm / 3 um = 733 px (the repo test set is rendered with a 640 px pinhole, 90 deg; the firmware and host take any calibration, see below).

What the code needs from the lens: nothing fixed. `firmware/core/atpose.c` and the host API take fx, fy, cx, cy and Brown-Conrady k1, k2, p1, p2, k3 from the calibration the user sends (`set_calibration`), so any lens works once it is calibrated; no code assumes 90 deg. Only the simulated dataset (`tools/geom.py`: 640 px, k1 = -0.18) and the housing cone depend on the nominal numbers. Versus the old 90 deg design: 15 % more pixels per tag at the same distance, 8 deg less horizontal coverage.

z stack above the PCB top (split plane z = 8.0 above the floor):
| Item | mm | Source |
|---|---|---|
| Sensor optical axis (CSP) | 0.7 | pcb_params.json |
| Holder height | 7.4 | CLA021 page |
| Lens top (front of the barrel) | 22.0 = 7.4 + 14.6 | allowance, see below |
| Hood rim | 22.3 | 0.3 beyond the lens front |
| Roof (flat) | 5.0 | housing.scad |

The lens length and back focal length are not on the Commonlands page; the mechanical drawing (STP) is behind a DocSend form and was not read. The 14.6 mm above the holder is therefore an allowance (2 mm more than the old 20.0 mm total), not a measurement. Replace it with the STP value when it is available (edit `lens_total_height_above_holder` in `pcb/pcb_params.json`, run `gen_params.py`, rebuild, run the tests).

Cone clearance: radius r(d) = r0 + d tan(50 deg) at distance d beyond the front element (tan = 1.192), r0 = 5.0 mm assumed clear radius of the front element. Hood rim at d = 0.3 mm: required 5.36 mm, bore radius 7.5 mm, margin 2.14 mm. Worst case with r0 = 7.0 mm (the whole barrel): 7.36 mm, margin 0.14 mm. Inside the hood the cylindrical bore is wider than the cone at every height, so there is no vignetting. Barrel 14.0 in a 15.0 bore leaves 0.5 mm radial clearance.

Holder headroom: the holder body (17 x 17, corner radius 12.0 from the axis) and an assumed screw-ear envelope (23 x 6 mm, corner radius 11.9) top out at 7.4 mm. The inner 45 deg cone roof is 9.1 mm high at that radius, so the clearance is 1.7 mm. (A full 20 x 20 holder would have collided: the cone is only 6.96 mm high at its 14.14 mm corner.) Checked in `tests/test_housing.py::test_holder_headroom_under_cone_roof`.

Holder screws (M1.6 x 5, thread-forming): they are assumed to be driven from the PCB underside up through the PCB into the holder ears (standard practice; the Commonlands pages do not say), so the heads sit under the board in the 4.0 mm gap to the floor (nothing else is near (+-10, 9) on the back shell). Engagement in the holder: 5.0 - 1.6 = 3.4 mm, which does not reach the holder top (7.4 mm). Head size: Commonlands does not publish it. McMaster 99461A911 (the part Commonlands points to) is listed second-hand as 2.6 mm diameter x 1.1 mm high; ISO 7045 M1.6 pan head is 3.2 x 1.3 mm. The design allows 3.4 x 1.3 mm, which leaves 2.7 mm to the floor (`test_holder_screw_heads_fit_under_pcb`). **Open PCB issue:** the footprint (`pcb/build_pcb.py`, `make_lens_mount_fp`) has 2.6 mm holes at (+-10, 9). A head of 2.6 mm (or even 3.2 mm with only 0.3 mm of bearing) does not bear on that. The holes should be about 1.9 mm (shank 1.6 mm plus clearance) so the head bears on the FR4. This PR does not touch `pcb/` other than `pcb_params.json`.

Printability: walls 2.4 mm, hood wall 2.0 mm (17.3 mm tall, vertical), cone roof 45 deg (no supports), USB-C cut-out roof bridges 9.3 mm. None of these changed except the hood, which is 2.0 mm taller. Assembly clearances are checked in the tests: M2 screw heads (3.4 x 1.3) in the 4.4 x 1.4 counterbores, USB-C body and opening, boot hole, FPGA and vents, LED bores and symbols, holder and lens envelope inside the front cover.

## Assumptions / issues for the PCB engineer
* USB-C body assumed 3.2 mm tall, spanning x -24 to -16.7; opening centred at z = PCB bottom - 1.6.
* FPGA centre (0,-8) taken from keepout_note.
* LEDs D1 PWR (-21.5, -6.5) and D2 STAT (-21.5, -9.5) (their 1k resistors R14/R15 are on the top side next to them, at x = -18.7) are 21.5 mm from the lens axis (0, 9), i.e. beyond the 18.5 mm cone start radius (boss edge at 19.4 mm), so the roof above them is flat (5.0 mm above the split plane) and the 2.0 mm bores are perpendicular to it. The LED well under the roof is a hull of two 2.4 x 1.6 mm pockets. Checked in `tests/test_housing.py::test_led_light_pipe_bores_go_through_flat_roof`.
* No STEP/STL of the board existed in `pcb/output`, so interference uses boxes from params (tests).
* Screw heads must be <= 4.4 mm dia and <= 1.4 mm tall (pan head M2: 3.8 x 1.3).
* Lens-holder screw holes: see the optics section; reduce the 2.6 mm NPTH at (+-10, 9) to about 1.9 mm.
