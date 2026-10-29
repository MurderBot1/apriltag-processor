#!/bin/bash
# per-module standalone synthesis + place&route at 100 MHz (FF-to-FF fmax per block)
export PATH=/c/msys64/ucrt64/bin:$PATH
cd "$(dirname "$0")/.."
m=$1; shift
files="$@"
yosys -q -p "read_verilog -sv $files; synth_ecp5 -noabc9 -top $m -json sim/mod_$m.json" > sim/mod_$m.ys.log 2>&1
nextpnr-ecp5 --85k --package CABGA381 --speed 8 --json sim/mod_$m.json --freq 100 --seed 1 --timing-allow-fail --log sim/mod_$m.pnr.log > /dev/null 2>&1
echo "$m: $(grep -E 'Max frequency for clock' sim/mod_$m.pnr.log | tail -1 | cut -c1-120)" > sim/mod_$m.result
