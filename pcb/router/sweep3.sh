#!/bin/bash
cd "$(dirname "$0")"
for sd in 3 4 5 6 7 8 9 10; do
  echo "SEED=$sd: $(W0=0.10 VIA_COST=9 SEED=$sd PFMAX=6 HINC=1.5 POLISH=400 ./router9.exe ../output/problem.txt ../output/sol_L3_$sd.txt 16 120 200 2>&1 | grep -E 'DONE')"
done
echo ALLDONE
