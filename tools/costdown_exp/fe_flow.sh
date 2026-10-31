#!/bin/bash
# usage: tools/costdown_exp/fe_flow.sh <25k|45k|85k> <speed 6|7|8> [seed] -- front-end-only design (fe_top.v) place & route, prints fmax per clock
export PATH=/c/msys64/ucrt64/bin:$PATH
cd "$(dirname "$0")/../.."; mkdir -p sim
DEV=$1; SP=$2; SEED=${3:-1}
[ -f sim/fe.json ] || yosys -q -p "read_verilog -sv rtl/csi2_rx.v rtl/thresh_binarize.v rtl/despeckle.v rtl/dphy_lane.v rtl/async_fifo.v rtl/dphy_rx.v rtl/sys_pll.v tools/costdown_exp/fe_top.v; synth_ecp5 -noabc9 -top fe_top -json sim/fe.json" > /dev/null 2>&1
PKG=CABGA256; [ $DEV = 85k ] && PKG=CABGA381
nextpnr-ecp5 --$DEV --package $PKG --speed $SP --json sim/fe.json --lpf tools/costdown_exp/fe_cabga256.lpf --lpf-allow-unconstrained --freq 85.714 --timing-allow-fail --seed $SEED --log sim/fe_${DEV}_${SP}_${SEED}.log -q > /dev/null 2>&1
grep -E "Max frequency for clock|ERROR|DP16KD|TRELLIS_COMB|LUT4" sim/fe_${DEV}_${SP}_${SEED}.log | tail -8
