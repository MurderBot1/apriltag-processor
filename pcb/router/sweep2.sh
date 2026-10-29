#!/bin/bash
cd "$(dirname "$0")"
for vc in 6 9; do for sd in 1 2 3 4 5 6 7 8; do
  echo "VC=$vc SEED=$sd: $(W0=0.10 VIA_COST=$vc SEED=$sd PFMAX=6 HINC=1.5 POLISH=300 ./router6.exe ../output/problem.txt ../output/sol_q_${vc}_$sd.txt 16 90 150 2>&1 | grep DONE)"
done; done
echo ALLDONE
