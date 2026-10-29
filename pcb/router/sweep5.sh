#!/bin/bash
cd "$(dirname "$0")"
for sd in 1 2 3 4 5 6; do
  r=$(IN2_PEN=2 W0=0.10 VIA_COST=9 SEED=$sd PFMAX=6 HINC=1.5 POLISH=500 ./router11.exe ../output/problem.txt ../output/sol_J_$sd.txt 16 150 250 2>&1 | grep -E 'DONE' | sed -E 's/DONE ([0-9.]+)s.*unrouted jobs ([0-9]+).*signals\) ([0-9]+)/time \1 unrouted \2 viol \3/')
  echo "SEED=$sd: $r in2=$(grep -c '^T [^ ]* 2 ' ../output/sol_J_$sd.txt)"
done
echo ALLDONE
