/* Minimal startup for sky130_vex2_soc (RV32IM, bare metal). */
  .section .text.init, "ax", @progbits
  .global _start
  .type   _start, @function
_start:
  .option push
  .option norelax
  la   gp, __global_pointer$
  .option pop
  la   sp, _stack_start

  /* Clear .bss */
  la   a0, _bss_start
  la   a1, _bss_end
1:
  bgeu a0, a1, 2f
  sw   zero, 0(a0)
  addi a0, a0, 4
  j    1b
2:
  call main

  /* If main returns, halt with its return value (or 0xDEAD if 0). */
  beqz a0, 3f
  j    4f
3:
  li   a0, 0xDEAD
4:
  li   a1, 0x20000000
  sw   a0, 0(a1)
5:
  j    5b
  .size _start, .-_start
