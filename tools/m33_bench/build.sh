#!/bin/sh
# Build the Cortex-M33 benchmark image: tools/m33_bench/build.sh [opt-flag] [outdir]   (default -O2, sim/m33)
export PATH=/c/msys64/ucrt64/bin:$PATH
OPT=${1:--O2}; OUT=${2:-sim/m33}
cd "$(dirname "$0")/../.."
mkdir -p "$OUT"
arm-none-eabi-gcc -mcpu=cortex-m33 -mthumb -mfloat-abi=softfp -mfpu=fpv5-sp-d16 $OPT -g0 -ffreestanding -fno-builtin -nostdlib \
    -ffunction-sections -fdata-sections -Wall -Wextra -DATTPU_FAST= \
    -Wl,-T,tools/m33_bench/link.ld -Wl,--gc-sections -Wl,-Map,$OUT/bench.map -Wl,-e,bench_run -Wl,-u,bench_init \
    -o $OUT/bench.elf tools/m33_bench/bench.c firmware/core/attpu.c -lgcc 2>&1 || exit 1
arm-none-eabi-objcopy -O binary $OUT/bench.elf $OUT/bench.bin
arm-none-eabi-size $OUT/bench.elf
