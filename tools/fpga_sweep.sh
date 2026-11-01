#!/bin/bash
# Run tools/fpga_flow.sh for several seeds in parallel and print a markdown table of the FINAL (post-route) nextpnr numbers.
# usage: tools/fpga_sweep.sh "<seeds, e.g. 1 2 3 4 5 6>" [speed (default 8)] [device 45k|25k (default 45k)] [freq (default 85.714)]
# Output dirs: sim/sweep_<device>_g<speed>_s<seed>/.   nextpnr numbers are estimates, not signoff.
# Exit status 0 if at least one seed closes every clock (core clk100 at <freq>, D-PHY sclk at 200 MHz), else 1.
cd "$(dirname "$0")/.."
SEEDS=${1:-1}; SPEED=${2:-8}; DEV=${3:-45k}; FREQ=${4:-85.714}
for s in $SEEDS; do FPGA_SPEED=$SPEED FPGA_DEVICE=$DEV FPGA_OUT=sim/sweep_${DEV}_g${SPEED}_s$s bash tools/fpga_flow.sh $s $FREQ >/dev/null 2>&1 & done
wait
echo "| seed | core clk100 fmax (target $FREQ) | D-PHY sclk fmax (target 200) | LUT4 | DP16KD | both close |"
echo "|---|---|---|---|---|---|"
ok=1
for s in $SEEDS; do
  d=sim/sweep_${DEV}_g${SPEED}_s$s; L=$d/nextpnr.log
  core=$(grep "Max frequency for clock" $L | tail -2 | grep "clk100" | sed "s/.*': //")
  dphy=$(grep "Max frequency for clock" $L | tail -2 | grep "dphy.sclk" | sed "s/.*': //")
  lut=$(grep "TRELLIS_COMB:" $L | tail -1 | sed 's/.*COMB: *//' | tr -s ' ')
  bram=$(grep "DP16KD:" $L | tail -1 | sed 's/.*DP16KD: *//' | tr -s ' ')
  if [ -n "$core" ] && ! echo "$core $dphy" | grep -q FAIL; then both=yes; ok=0; else both=no; fi
  echo "| $s | ${core:-n/a} | ${dphy:-n/a} | $lut | $bram | $both |"
done
exit $ok
