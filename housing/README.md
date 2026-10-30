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
* PCB is captured: lateral 0.2 mm clearance in the cavity (+ screw shanks in the 2.2 mm holes), vertical clamp between the four post shoulders and the four front bosses; top parts (lens holder 6 mm) have 0.9 mm headroom under the cone roof, bottom parts 0.8 mm.
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
2. Fit the lens holder/lens (barrel top 20.0 mm above the PCB).
3. Insert the light pipes into the front cover bores from below (or from above after assembly).
4. Lower the FRONT cover over the lens so the tongue enters the groove.
5. Turn the housing over, drive four M2 x 10 screws up through the back posts into the front bosses (do not over-tighten; PLA).
6. Boot button: press with a 2 mm pin through the hole in the floor.

## Dimension table
| Item | mm |
|---|---|
| Outer footprint | 53.2 x 53.2, corner R3 |
| Overall height (assembled) | 28.3 (split plane at z = 8.0, back incl. tongue 9.5) |
| Cavity (lateral) | 48.4 x 48.4 (0.2 per side) |
| Wall / floor / roof (vertical) | 2.4 / 2.4 / 2.4; hood wall 2.0 |
| PCB bottom / top above outer floor | 6.4 / 8.0 |
| Floor to PCB (bottom parts 3.2 mm) | 4.0 |
| Lens aperture (bore) | 15.0 dia, axis at (0, +9) |
| Hood rim above PCB top | 20.3 (lens front at 20.0) |
| Hood height above front-cover flat roof (5.0) | 15.3 |
| USB-C opening | 9.34 x 3.66, centre z = 4.8, y = -8 |
| Boot hole | 2.5 dia at (20, 4) |
| Vents | 5 slots 1.6 x 14, pitch 3.4, centred on (0,-8) |
| Screws | M2 x 10 at (+-20.5, +-20.5) |

## FOV clearance calculation
Lens: f = 1.92 mm, HFOV = 90 deg. Sensor OV9281 1280 x 800 at 3 um pixels (active 3.84 x 2.40 mm): HFOV = 2 atan(1.92/1.92) = 90 deg (check). Half diagonal = sqrt(1.92^2 + 1.20^2) = 2.264 mm, so diagonal half-angle = atan(2.264/1.92) = 49.7 deg (DFOV 99.4 deg). Design uses 49.7 deg (worst case).

Cone leaving the lens: radius r(d) = r0 + d tan(49.7 deg) at distance d beyond the front-element plane (tan = 1.179), with r0 = 5.0 mm assumed clear radius of the front element (the 14 mm is the barrel OD; the pupil is behind the front glass, so this is conservative).

Hood rim is d = 0.3 mm beyond the lens front (20.3 vs 20.0 above PCB top): required radius = 5.0 + 0.3 x 1.179 = 5.35 mm. Bore radius is 7.5 mm, so margin = 2.15 mm. Worst case using the entire barrel radius (7.0 mm) as r0: 7.35 mm, margin 0.15 mm. Inside the hood the bore (cylinder) is wider than the cone at every height, so there is no vignetting. Barrel (14.0) in bore (15.0) leaves 0.5 mm radial clearance; holder (20 x 20 x 6, centred on the axis) has 0.9 mm headroom under the roof at its corners (cone roof height 6.96 at r = 14.14 from the axis). Total stack: holder 6 + barrel 14 = 20 mm above the PCB, hood rim 20.3 mm.
These are checked in `tests/test_housing.py` by sampling the cone against the front STL.

## Assumptions / issues for the PCB engineer
* USB-C body assumed 3.2 mm tall, spanning x -24 to -16.7; opening centred at z = PCB bottom - 1.6.
* FPGA centre (0,-8) taken from keepout_note.
* LEDs D1 PWR (-21.5, -6.5) and D2 STAT (-21.5, -9.5) (their 1k resistors R14/R15 are on the top side next to them, at x = -18.7) are 21.5 mm from the lens axis (0, 9), i.e. beyond the 18.5 mm cone start radius (boss edge at 19.4 mm), so the roof above them is flat (5.0 mm above the split plane) and the 2.0 mm bores are perpendicular to it. The LED well under the roof is a hull of two 2.4 x 1.6 mm pockets. Checked in `tests/test_housing.py::test_led_light_pipe_bores_go_through_flat_roof`.
* No STEP/STL of the board existed in `pcb/output`, so interference uses boxes from params (tests).
* Screw heads must be <= 4.4 mm dia and <= 1.4 mm tall (pan head M2: 3.8 x 1.3).
