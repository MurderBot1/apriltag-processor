#!/bin/sh
# Pose solver for the Cortex-M33 emulator: tools/m33_bench/build_pose.sh "<compiler flags>" [outdir]
# e.g. "-O2 -include tgmath.h" (float maths: sqrtf/atan2f on the single-precision FPU) or "-O2" (double maths in software: upper bound,
# the RP2350 SDK maps double to the DCP coprocessor which the emulator does not model).
export PATH=/c/msys64/ucrt64/bin:$PATH
OPT=${1:--O2}; OUT=${2:-sim/m33pose}
cd "$(dirname "$0")/../.."
mkdir -p "$OUT"
arm-none-eabi-gcc -mcpu=cortex-m33 -mthumb -mfloat-abi=hard -mfpu=fpv5-sp-d16 $OPT -g0 -ffunction-sections -fdata-sections -Wall \
    -Wl,-T,tools/m33_bench/link_pose.ld -Wl,--gc-sections -Wl,-Map,$OUT/bench.map -Wl,-e,bench_run \
    -o $OUT/bench.elf tools/m33_bench/pose_bench.c firmware/core/atpose.c --specs=nosys.specs -lm -lc -lgcc 2>&1 || exit 1
arm-none-eabi-objcopy -O binary $OUT/bench.elf $OUT/bench.bin
arm-none-eabi-size $OUT/bench.elf
