MEMORY { FLASH (rx) : ORIGIN = 0x10000000, LENGTH = 1M
         RAM (rwx)  : ORIGIN = 0x20000000, LENGTH = 256K }
SECTIONS {
  .text : { *(.text*) *(.rodata*) *(.eh_frame*) } > FLASH
  .bss (NOLOAD) : { *(.bss*) *(COMMON) } > RAM
  /DISCARD/ : { *(.ARM.exidx*) *(.comment) }
}
