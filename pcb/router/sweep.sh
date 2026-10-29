#!/bin/bash
cd "$(dirname "$0")"
for cfg in "6 1.5 0" "6 1.0 0.3" "12 2 0.5" "3 1 0.2" "8 3 0"; do set -- $cfg
  echo "PFMAX=$1 HINC=$2 HGROW=$3: $(PFMAX=$1 HINC=$2 HGROW=$3 ./router.exe ../output/problem.txt ../output/sol_$1_$2_$3.txt 16 90 120 2>&1 | grep DONE)"
done
