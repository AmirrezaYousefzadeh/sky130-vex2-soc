/* Linker script for sky130_vex2_soc (true Harvard)
 *   IMEM  0x00000000  8 KiB  (.text)
 *   DMEM  0x10000000  8 KiB  (.rodata/.data/.bss/stack)
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
  IMEM (rx) : ORIGIN = 0x00000000, LENGTH = 8K
  DMEM (rw) : ORIGIN = 0x10000000, LENGTH = 8K
}

_stack_size = 512;

SECTIONS {
  .text : {
    *(.text.init)
    *(.text .text.*)
    *(.text.startup)
  } > IMEM

  .rodata : {
    . = ALIGN(4);
    *(.rodata .rodata.*)
    *(.srodata .srodata.*)
    *(.rdata)
  } > DMEM

  .data : {
    . = ALIGN(4);
    *(.data .data.*)
    *(.sdata .sdata.*)
    . = ALIGN(8);
    PROVIDE(__global_pointer$ = . + 0x800);
  } > DMEM

  .bss (NOLOAD) : {
    . = ALIGN(4);
    _bss_start = .;
    *(.sbss .sbss.*)
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(4);
    _bss_end = .;
  } > DMEM

  /* Stack grows down from the top of DMEM; not a real section payload. */
  PROVIDE(_stack_start = ORIGIN(DMEM) + LENGTH(DMEM));
  PROVIDE(_stack_end   = _stack_start - _stack_size);

  /DISCARD/ : {
    *(.eh_frame*)
    *(.comment)
    *(.note*)
  }
}
