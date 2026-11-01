#!/usr/bin/env python3
"""Report the RP2350 firmware image size against the flash and SRAM limits.

usage: tools/fw_size.py ELF [--size-tool arm-none-eabi-size] [--out report.md]

Reads `arm-none-eabi-size -A` and sorts every allocated section by address:
  0x10000000.. = XIP flash (16 MB fitted, see pcb_pins.h), 0x20000000.. = SRAM (520 KB on the RP2350).
The flash use is the size of the .bin (the image as loaded) when given with --bin, otherwise the sum of the sections
linked into flash. SRAM use is the sum of the sections linked into SRAM.
Exit code 1 if the image does not fit.
"""
import argparse, subprocess, sys, os

FLASH_BASE, FLASH_SIZE = 0x10000000, 16 * 1024 * 1024
SRAM_BASE, SRAM_SIZE = 0x20000000, 520 * 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('elf')
    ap.add_argument('--size-tool', default='arm-none-eabi-size')
    ap.add_argument('--bin', help='.bin file (flash image as loaded); its size is the flash use')
    ap.add_argument('--uf2', help='.uf2 file (reported only)')
    ap.add_argument('--out')
    a = ap.parse_args()
    txt = subprocess.run([a.size_tool, '-A', a.elf], capture_output=True, text=True, check=True).stdout
    flash_secs, sram_secs = [], []
    for line in txt.splitlines():
        p = line.split()
        if len(p) != 3 or not p[1].isdigit():
            continue
        name, size, addr = p[0], int(p[1]), int(p[2])
        if size == 0 or addr == 0:
            continue
        if FLASH_BASE <= addr < FLASH_BASE + 0x1000000:
            flash_secs.append((name, size, addr))
        elif SRAM_BASE <= addr < SRAM_BASE + 0x100000:
            sram_secs.append((name, size, addr))
    sram_used = sum(s for _, s, _ in sram_secs)
    flash_img = os.path.getsize(a.bin) if a.bin else sum(s for _, s, _ in flash_secs)
    ok = sram_used <= SRAM_SIZE and flash_img <= FLASH_SIZE
    L = ['### RP2350 firmware image size', '',
         '| region | used (bytes) | limit (bytes) | used % |', '|---|---:|---:|---:|',
         f'| flash image (.bin, loaded) | {flash_img} | {FLASH_SIZE} | {100 * flash_img / FLASH_SIZE:.2f} |',
         f'| SRAM static (.data + .bss + RAM code + stacks) | {sram_used} | {SRAM_SIZE} | {100 * sram_used / SRAM_SIZE:.2f} |',
         f'| SRAM left for heap/runtime | {SRAM_SIZE - sram_used} | | |']
    if a.uf2:
        L.append(f'| .uf2 file (flash image in 256-byte blocks, 512 B each) | {os.path.getsize(a.uf2)} | | |')
    L += ['', 'SRAM sections (sorted by size):', '', '| section | bytes | address |', '|---|---:|---|']
    for n, s, ad in sorted(sram_secs, key=lambda x: -x[1]):
        L.append(f'| {n} | {s} | 0x{ad:08x} |')
    L += ['', 'Flash sections (link addresses in XIP space):', '', '| section | bytes | address |', '|---|---:|---|']
    for n, s, ad in sorted(flash_secs, key=lambda x: -x[1]):
        L.append(f'| {n} | {s} | 0x{ad:08x} |')
    L += ['', f'Result: {"fits" if ok else "DOES NOT FIT"}. The SRAM figure is static allocation only; stack depth and DMA contention are not measured.']
    out = '\n'.join(L) + '\n'
    if a.out:
        os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
        open(a.out, 'w').write(out)
    print(out)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
