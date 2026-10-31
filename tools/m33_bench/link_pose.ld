MEMORY { FLASH (rx) : ORIGIN = 0x10000000, LENGTH = 1M
         RAM (rwx)  : ORIGIN = 0x20000000, LENGTH = 192K }
SECTIONS {
  .text : { *(.text*) *(.rodata*) *(.eh_frame*) *(.init*) *(.fini*) } > FLASH
  .data : { _sdata = .; *(.data*) _edata = .; } > RAM AT > FLASH
  _data_lma = LOADADDR(.data);
  .bss (NOLOAD) : { *(.bss*) *(COMMON) } > RAM
  /DISCARD/ : { *(.ARM.exidx*) *(.comment) *(.ARM.attributes) }
}
