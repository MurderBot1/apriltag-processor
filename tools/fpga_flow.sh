#!/bin/bash
# Open-source FPGA flow for the ECP5-45F (LFE5U-45F-8BG381C, architecture A3): yosys synthesis -> nextpnr-ecp5 place & route (+ timing report).
# usage: tools/fpga_flow.sh [seed] [freq_mhz]
export PATH=/c/msys64/ucrt64/bin:$PATH
cd "$(dirname "$0")/.."
SEED=${1:-1}; FREQ=${2:-100}
python tools/pins.py > /dev/null 2>&1 || py -3.12 tools/pins.py > /dev/null
yosys -l sim/yosys_top.log -p "read_verilog -sv rtl/csi2_rx.v rtl/thresh_binarize.v rtl/despeckle.v rtl/run_ccl.v rtl/mask_stream.v rtl/i2c_master.v rtl/sensor_init.v rtl/spi_slave.v rtl/cam_core.v rtl/dphy_lane.v rtl/async_fifo.v rtl/dphy_rx.v rtl/sys_pll.v rtl/apriltag_cam_top.v; synth_ecp5 -noabc9 -top apriltag_cam_top -json sim/top.json; stat" > sim/yosys_top.out 2>&1
nextpnr-ecp5 --45k --package CABGA381 --speed 8 --json sim/top.json --lpf rtl/apriltag_cam.lpf --freq $FREQ --textcfg sim/top.cfg --report sim/timing.json --seed $SEED --timing-allow-fail --log sim/nextpnr.log > sim/nextpnr.out 2>&1
ecppack --compress sim/top.cfg sim/apriltag_cam.bit > sim/ecppack.log 2>&1
echo FLOW_DONE >> sim/nextpnr.out
