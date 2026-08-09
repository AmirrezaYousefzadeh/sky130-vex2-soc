# Firmware

Bare-metal RISC-V firmware for `sky130_vex2_soc` (RV32IM, Harvard IMEM/DMEM).

## Quick start

```bash
# needs riscv-none-elf-gcc — see ../setup/install_riscv_toolchain.sh
make -C firmware all
```

Produces under `firmware/build/`:

- `mnist_mlp.elf` / `.dis` / `.map`
- `imem.hex`, `dmem.hex` — loaded by the firmware testbench

Run on the RTL model:

```bash
./simulation/run_sim.sh fw
./simulation/run_sim.sh fw --vcd
# (aliases: firmware, mnist)
```

## Layout

| Path | Role |
|------|------|
| `mnist/mnist_mlp.c` | 3-layer FC net (`64→32→10`), int8 weights, 8×8 MNIST sample |
| `mnist/train_export.py` | Train + export `weights.h` (optional `make train`) |
| `common/soc.h` | `tohost` / memory-map helpers |
| `crt0.S`, `link.ld` | Startup + linker script (`.text`→IMEM, data→DMEM) |
| `scripts/elf2mem.py` | ELF → `imem.hex` / `dmem.hex` |

## Memory map (SoC)

| Region | Address | Size |
|--------|---------|------|
| IMEM | `0x0000_0000` | 8 KiB |
| DMEM | `0x1000_0000` | 8 KiB |
| tohost | `0x2000_0000` | write nonzero → halt + gate SRAM clocks |

PASS code: `tohost = predicted_digit + 1` (digits 0..9 → codes 1..10).
Schedule: init → sleep 10k → one inference → sleep 10k → halt (TB times sleeps).

## Toolchain

`Makefile` expects:

```text
tools/riscv-none-elf-gcc/bin/riscv-none-elf-gcc
```

Override with `TOOLCHAIN=/path/to/riscv-none-elf`.
