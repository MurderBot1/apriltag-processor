#!/bin/bash
# Open-source FPGA flow for the ECP5-45F (LFE5U-45F-8BG381C, architecture A3): yosys synthesis -> nextpnr-ecp5 place & route (+ timing report).
# usage: tools/fpga_flow.sh [seed (default 1: closes core 85.714 MHz and D-PHY 200 MHz)] [freq_mhz (default 85.714)]        env: FPGA_OUT=dir (default sim), FPGA_DEVICE=45k|85k|25k (default 45k), FPGA_SPEED=6|7|8 (ECP5 speed grade, default 8; 6 and 7 do NOT close timing, see docs/fpga.md)
export PATH=/c/msys64/ucrt64/bin:$PATH
cd "$(dirname "$0")/.."
SEED=${1:-1}; FREQ=${2:-85.714}; OUT=${FPGA_OUT:-sim}; DEV=${FPGA_DEVICE:-45k}; SPEED=${FPGA_SPEED:-8}
mkdir -p "$OUT"
echo "fpga_flow: device=$DEV package=CABGA381 speed=$SPEED seed=$SEED freq=$FREQ" > $OUT/flow_params.txt
python tools/pins.py > /dev/null 2>&1 || py -3.12 tools/pins.py > /dev/null
yosys -l $OUT/yosys_top.log -p "read_verilog -sv rtl/csi2_rx.v rtl/thresh_binarize.v rtl/despeckle.v rtl/run_ccl.v rtl/mask_stream.v rtl/i2c_master.v rtl/sensor_init.v rtl/spi_slave.v rtl/cam_core.v rtl/dphy_lane.v rtl/async_fifo.v rtl/dphy_rx.v rtl/sys_pll.v rtl/apriltag_cam_top.v; synth_ecp5 -noabc9 -top apriltag_cam_top -json $OUT/top.json; stat" > $OUT/yosys_top.out 2>&1
nextpnr-ecp5 --$DEV --package CABGA381 --speed $SPEED --json $OUT/top.json --lpf rtl/apriltag_cam.lpf --freq $FREQ --textcfg $OUT/top.cfg --report $OUT/timing.json --seed $SEED --timing-allow-fail --log $OUT/nextpnr.log > $OUT/nextpnr.out 2>&1
ecppack --compress $OUT/top.cfg $OUT/apriltag_cam.bit > $OUT/ecppack.log 2>&1
echo FLOW_DONE >> $OUT/nextpnr.out
