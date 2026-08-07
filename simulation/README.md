# Simulation

Icarus Verilog RTL sims for `sky130_vex2_soc`. Waveforms (VCD) are written into **this folder**.

## Quick start

```bash
source ../env.sh   # optional: puts OSS CAD Suite on PATH
./run_sim.sh       # smoke test → simulation/sky130_vex2_soc.vcd
./run_sim.sh fw    # build + run MNIST MLP firmware (no VCD by default)
./run_sim.sh fw --vcd
```

Open `*.vcd` in Cursor with the **Surfer** or **VaporView** extension, or GTKWave.

## Modes

| Mode | What it does | Default VCD |
|------|----------------|-------------|
| `smoke` | Tiny hand-loaded program writes `tohost` and halts | `sky130_vex2_soc.vcd` |
| `fw` | Builds firmware (`fw/`) and runs MNIST MLP until halt | off unless `--vcd` |

PASS for firmware: `tohost = predicted_digit + 1` and SRAM clocks gated.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DUMP_VCD=1` | off for `fw`, on for `smoke` | Write a VCD under `simulation/` |
| `--vcd` / `--no-vcd` | — | CLI flags for firmware mode |
| `VCD_NAME=foo.vcd` | mode-specific | Output filename in this folder |
| `TIMEOUT_CYCLES` | `5000000` | Firmware halt timeout (clock cycles) |
| `HARDWARE_TOOLS_ROOT` | `/media/hardware_design_tools` | OSS CAD Suite (`iverilog` / `vvp`) |

Build artifacts go to `simulation/build/` (gitignored). Testbenches: `tb_sky130_vex2_soc.v`, `tb_fw_mnist.v`.

## Requirements

- Icarus Verilog (`iverilog`, `vvp`) — see `../setup/`
- For `fw`: RISC-V toolchain under `../tools/riscv-none-elf-gcc` (see `../setup/`)
