// AprilTag camera housing - two printable parts (FRONT cover, BACK shell).
// Mechanical contract: ../pcb/pcb_params.json.  All units mm.
// Frame: origin at board centre, +X right / +Y up when looking at the LENS side,
// +Z toward the lens.  z=0 is the outside bottom of the BACK shell.
//
// Render a part:  openscad -D 'part="front"' -o output/front.stl housing.scad
//   part = "back" | "front" | "assembly" | "exploded"
part = "assembly";
$fn = 64;

// ---------------- PCB contract (generated: py gen_params.py) ----------------
include <pcb_params.scad>
fpga_c = [0, -8];   // from keepout_note

// ---------------- housing parameters ----------------
clr      = 0.2;               // lateral PCB clearance per side
wall     = 2.4;               // side wall (>= 1.6)
floor_t  = 2.4;               // back floor
standoff = bot_h + 0.8;       // PCB bottom above floor (0.8 under 3.2 parts)
hi = pcb_w/2 + clr;           // cavity half width  (21.2)
ho = hi + wall;               // outer half width   (23.6)
zpb = floor_t + standoff;     // PCB bottom plane
zpt = zpb + pcb_t;            // PCB top plane = split plane front/back
corner_r = 3;

screw_clear = 2.4;            // M2 clearance
head_cb_d = 4.4; head_cb_h = 1.4;
pilot_d = 1.8;                // self-tapping pilot (use 3.2 for M2 heat-set insert)
pilot_depth = 4.0;
post_d = 6;
holder_screw_hd_d = 3.4;      // holder screw head diameter allowance (Commonlands does not publish it; ISO 7045 M1.6 pan head is 3.2 max)
holder_screw_hd   = 1.3;      // head height allowance (ISO 7045 M1.6: 1.3 max); it sits under the PCB in the 4.0 mm gap above the floor

tongue_t = 1.0; tongue_h = 1.5; groove_extra = 0.2;   // lap joint, ring just outside cavity

// front cover (local z=0 is the split plane zpt)
roof_in  = 2.6; // flat inner roof height over PCB (2.0 top parts + 0.6)
roof_t   = 2.4;               // vertical roof thickness
cone_r0  = 18.5;              // cone starts here (45 deg, printable w/o supports)
bore_d   = 15.0;              // lens aperture (14 mm barrel + 0.5 per side)
hood_wall = 2.0;
hood_top = holder[2] + barrel_h + 0.3;   // rim 0.3 above lens front (holder 7.4 CLA021-LCP + lens allowance 14.6 = lens top 22.0 above the PCB)
cone_in_top = roof_in + (cone_r0 - bore_d/2);   // inner cone height at bore
led_bore = 2.0;               // for 1.75 mm clear filament light pipe; LEDs sit on the FLAT roof (> cone_r0 from the lens axis), bores are perpendicular to it

// LED function symbols, engraved into the flat outer roof beside each light-pipe bore (led_pos[0] = PWR, led_pos[1] = STAT, as in pcb_params.json)
sym_size  = 4.4;              // symbol envelope (square, mm)
sym_depth = 0.6;              // engraving depth (3 layers at 0.2); roof stays 1.8 thick under it
sym_w     = 0.8;              // stroke width (2 perimeters of a 0.4 nozzle)
sym_gap   = 0.8;              // clear distance bore edge -> symbol envelope
sym_dx    = 1.2;              // symbol centre shifted +X from the LED (keeps >= 1 mm from the left outer wall)

module stroke(a, b) { hull() { translate(a) circle(d = sym_w, $fn = 16); translate(b) circle(d = sym_w, $fn = 16); } }
module polyline(pts) { for (i = [0 : len(pts) - 2]) stroke(pts[i], pts[i + 1]); }

// IEC 5009 power symbol: ring open at the top with a vertical bar through the gap
module sym_power(s = sym_size) {
  ro = s/2;
  difference() {
    difference() { circle(r = ro, $fn = 48); circle(r = ro - sym_w, $fn = 48); }
    translate([-(sym_w + 1.2)/2, 0]) square([sym_w + 1.2, ro + 1]);     // gap in the top of the ring (0.6 each side of the bar)
  }
  hull() { translate([-sym_w/2, 0]) square([sym_w, 0.01]); translate([0, ro - sym_w/2]) circle(d = sym_w, $fn = 16); }
}

// heartbeat / pulse line: flat, up-spike, down-spike, flat (firmware heartbeat + status)
module sym_pulse(s = sym_size) {
  h = s/2 - sym_w/2;
  polyline([[-s/2 + sym_w/2, 0], [-s/2 + 1.3, 0], [-0.5, 0.8*h], [0.35, -h], [1.0, 0], [s/2 - sym_w/2, 0]]);
}

// centre of the symbol of LED i: beyond its bore, away from the other LED (PWR up, STAT down)
function sym_pos(i) = [led_pos[i][0] + sym_dx, led_pos[i][1] + (i == 0 ? 1 : -1) * (led_bore/2 + sym_gap + sym_size/2)];

module led_symbols(z0) {   // cutters from z0 upward
  translate([sym_pos(0)[0], sym_pos(0)[1], z0]) linear_extrude(sym_depth + 1) sym_power();
  translate([sym_pos(1)[0], sym_pos(1)[1], z0]) linear_extrude(sym_depth + 1) sym_pulse();
}

module rrect(w, r, h) { linear_extrude(h) offset(r) square(w - 2*r, center = true); }
function sgn() = [[1,1],[-1,1],[1,-1],[-1,-1]];

// ---------------- BACK shell ----------------
module back() {
  usb_zc = zpb - bot_h/2;
  difference() {
    union() {
      difference() {
        rrect(2*ho, corner_r, zpt);
        translate([-hi, -hi, floor_t]) cube([2*hi, 2*hi, zpt]);
      }
      // inner lap tongue
      translate([0, 0, zpt - 0.01]) linear_extrude(tongue_h + 0.01) difference() {
        square(2*(hi + tongue_t), center = true);
        square(2*hi, center = true);
      }
      // screw posts: PCB seating shoulders at z = zpb
      for (s = sgn()) hull() {
        translate([s[0]*hole_xy, s[1]*hole_xy, floor_t - 0.01]) cylinder(d = post_d, h = standoff + 0.01);
        translate([s[0]*(hi - 0.3), s[1]*(hi - 0.3), floor_t - 0.01]) cylinder(d = 1, h = standoff + 0.01);
      }
    }
    for (s = sgn()) translate([s[0]*hole_xy, s[1]*hole_xy, 0]) {
      translate([0, 0, -1]) cylinder(d = screw_clear, h = zpb + 2);
      translate([0, 0, -1]) cylinder(d = head_cb_d, h = head_cb_h + 1);
    }
    // USB-C opening 8.94x3.26 + 0.4 clearance through left wall
    translate([-ho - 1, usb_c[1] - (usb_w + 0.4)/2, usb_zc - (usb_h + 0.4)/2])
      cube([wall + 1 + 2.0, usb_w + 0.4, usb_h + 0.4]);
    // boot button access
    translate([boot_pos[0], boot_pos[1], -1]) cylinder(d = 2.5, h = floor_t + 2);
    // vent slots under FPGA (centre region)
    for (i = [-2:2]) translate([fpga_c[0] + i*3.4 - 0.8, fpga_c[1] - 7, -1]) cube([1.6, 14, floor_t + 2]);
  }
}

// ---------------- FRONT cover (print rim-down, as modelled) ----------------
module corner_bosses() {
  for (s = sgn()) hull() {
    translate([s[0]*hole_xy, s[1]*hole_xy, 0]) cylinder(d = post_d, h = roof_in + 0.2);
    translate([s[0]*(hi - 0.3), s[1]*(hi - 0.3), 0]) cylinder(d = 1, h = roof_in + 0.2);
  }
}

module outer_env() {   // outer solid of the front cover (axis at sensor_c)
  intersection() {
    rrect(2*ho, corner_r, hood_top);
    union() {
      rrect(2*ho, corner_r, roof_in + roof_t);
      translate([sensor_c[0], sensor_c[1], 0]) rotate_extrude() polygon([[0,0],[cone_r0,0],[cone_r0, roof_in + roof_t],
          [bore_d/2 + hood_wall, roof_in + roof_t + cone_r0 - bore_d/2 - hood_wall], [bore_d/2 + hood_wall, hood_top], [0, hood_top]]);
    }
  }
}

module front() {
  difference() {
    union() {
      difference() {
        outer_env();
        // cavity: flat roof + 45 deg cone around the lens axis, clipped to the cavity walls
        intersection() {
          translate([-hi, -hi, -1]) cube([2*hi, 2*hi, hood_top]);
          union() {
            translate([-hi, -hi, -1]) cube([2*hi, 2*hi, 1 + roof_in]);
            translate([sensor_c[0], sensor_c[1], 0]) rotate_extrude()
              polygon([[0,-1],[cone_r0 + roof_in + 1,-1],[bore_d/2, cone_in_top],[0, cone_in_top]]);
          }
        }
      }
      intersection() {
        outer_env();
        union() {
          corner_bosses();
          hull() for (p = led_pos) translate([p[0], p[1], 0]) cylinder(d = 4.2, h = hood_top);
        }
      }
    }
    translate([0, 0, -1]) linear_extrude(1 + tongue_h + groove_extra) difference() {
      square(2*(hi + tongue_t + groove_extra), center = true);
      square(2*hi - 0.001, center = true);
    }
    // LED well under the roof (both LEDs, 1.6 x 0.8 bodies + margin)
    hull() for (p = led_pos) translate([p[0] - 1.2, p[1] - 0.8, -1]) cube([2.4, 1.6, 1 + 1.2]);
    for (p = led_pos) translate([p[0], p[1], 0.5]) cylinder(d = led_bore, h = hood_top);
    led_symbols(roof_in + roof_t - sym_depth);
    for (s = sgn()) translate([s[0]*hole_xy, s[1]*hole_xy, -1]) cylinder(d = pilot_d, h = pilot_depth + 1);
    translate([sensor_c[0], sensor_c[1], -1]) cylinder(d = bore_d, h = hood_top + 2);
  }
}

// ---------------- PCB mock-up (boxes) ----------------
module pcb_model() {
  color("green") translate([0, 0, zpb]) rrect(pcb_w, 2, pcb_t);
  translate([sensor_c[0], sensor_c[1], 0]) {
    color("gray") translate([-holder[0]/2, -holder[1]/2, zpt]) cube(holder);
    color("gray") translate([-holder_ears[0]/2, -holder_ears[1]/2, zpt]) cube([holder_ears[0], holder_ears[1], holder[2]]);   // assumed screw-ear envelope
    color("black") translate([0, 0, zpt + holder[2]]) cylinder(d = barrel_d, h = barrel_h);
    color("white") translate([-sensor_pkg[0]/2, -sensor_pkg[1]/2, zpt - 0.01]) cube([sensor_pkg[0], sensor_pkg[1], 0.5]);
  }
  // holder screws: M1.6 x 5 from the PCB underside, head under the board (head 3.4 x 1.3 allowance, hole in PCB 2.6)
  for (sx = [-1, 1]) color("silver") translate([sx*10, sensor_c[1], zpb - holder_screw_hd]) cylinder(d = holder_screw_hd_d, h = holder_screw_hd);
  for (p = led_pos) color("red") translate([p[0] - 0.8, p[1] - 0.4, zpt]) cube([1.6, 0.8, 0.8]);
  color("darkgray") translate([fpga_c[0] - 8.5, fpga_c[1] - 8.5, zpb - 1.5]) cube([17, 17, 1.5]);
  color("silver") translate([usb_c[0], usb_c[1] - usb_w/2, zpb - bot_h]) cube([7.3, usb_w, bot_h]);
  color("blue") translate([boot_pos[0] - 1.75, boot_pos[1] - 1.75, zpb - bot_h]) cube([3.5, 3.5, bot_h]);
}

if (part == "back") back();
else if (part == "front") front();
else if (part == "assembly") {
  color("orange", 0.9) back();
  color("steelblue", 0.6) translate([0, 0, zpt]) front();
  pcb_model();
} else if (part == "exploded") {
  color("orange") back();
  translate([0, 0, 12]) pcb_model();
  color("steelblue") translate([0, 0, zpt + 30]) front();
}
