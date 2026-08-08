# Simulation

Icarus Verilog sims for `sky130_vex2_soc`. Waveforms (VCD) are written into **this folder**.

| Script | Level | Typical use |
|--------|-------|-------------|
| `run_sim.sh` | RTL | Fast functional / firmware bring-up |
| `run_gls.sh` | Gate (post-PnR netlist) | Toggle activity for **power** |

## Quick start

```bash
source ../env.sh   # optional: puts OSS CAD Suite on PATH

# RTL
./run_sim.sh                 # smoke → sky130_vex2_soc.vcd
./run_sim.sh fw              # MNIST MLP firmware (no VCD by default)
./run_sim.sh fw --vcd

# Gate-level (needs a finished OpenLane run with final/nl/)
./run_gls.sh                 # smoke → sky130_vex2_soc_gls.vcd
./run_gls.sh fw --vcd        # → mnist_mlp_gls.vcd  (use this for power)
```

Then:

```bash
../power/run_power.sh ./mnist_mlp_gls.vcd
```

Open `*.vcd` in Cursor with the **Surfer** or **VaporView** extension, or GTKWave.

## Modes

| Mode | What it does | Default VCD (RTL / GLS) |
|------|----------------|-------------------------|
| `smoke` | Tiny hand-loaded program writes `tohost` and halts | `sky130_vex2_soc.vcd` / `*_gls.vcd` |
| `fw` | Builds firmware (`firmware/`) and runs MNIST MLP until halt | off unless `--vcd` |

PASS for firmware: `tohost = predicted_digit + 1` and SRAM clocks gated.

## Parameters (both scripts)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DUMP_VCD=1` | off for `fw`, on for `smoke` | Write a VCD under `simulation/` |
| `--vcd` / `--no-vcd` | — | CLI flags for firmware mode |
| `VCD_NAME=foo.vcd` | mode-specific | Output filename in this folder |
| `TIMEOUT_CYCLES` | `5000000` | Firmware halt timeout (clock cycles) |
| `HARDWARE_TOOLS_ROOT` | `/media/hardware_design_tools` | OSS CAD Suite (`iverilog` / `vvp`) |

### GLS-only

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RUN_DIR` | `synthesis/.../runs/sky130_vex2_soc_v2` | OpenLane run providing `final/nl/*.nl.v` |
| `DUMP_LEVEL` | `1` | `$dumpvars` depth — `1` = SoC nets only (recommended for power) |
| `PDK_ROOT` | `/media/pdk` | `sky130_fd_sc_hd` Verilog + primitives |

GLS uses **FUNCTIONAL** (zero-delay) cell models and the behavioral SRAM22 model so `$readmemh` backdoor load still works. No SDF annotation in this flow.

The synthesized CPU regfile is `$deposit`ed to zero at time 0 (`gen_gls_regfile_init.py`) to match the RTL `$readmemb` of `VexRiscv2.v_toplevel_RegFilePlugin_regFile.bin`.

Build artifacts: `simulation/build/` (RTL), `simulation/build_gls/` (gate). Testbenches: `tb_sky130_vex2_soc.v`, `tb_fw_mnist.v`.

## Requirements

- Icarus Verilog (`iverilog`, `vvp`) — see `../setup/`
- For `fw` / `firmware`: RISC-V toolchain under `../tools/riscv-none-elf-gcc` (see `../setup/`)
- For GLS: completed synthesis run + PDK cell Verilog
