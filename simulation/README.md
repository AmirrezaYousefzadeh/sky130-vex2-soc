# Simulation

Icarus Verilog sims for `sky130_vex2_soc`. Waveforms (VCD) are written into **this folder**.

| Script | Level | Typical use |
|--------|-------|-------------|
| `run_sim.sh` | RTL | Fast functional / firmware bring-up |
| `run_gls.sh` | Gate (post-PnR netlist + **SDF**) | Toggle activity / glitches for **power** |

## Quick start

```bash
source ../env.sh   # optional: puts OSS CAD Suite on PATH

# RTL
./run_sim.sh                 # smoke → waveform.vcd
./run_sim.sh fw              # MNIST MLP firmware (no VCD by default)
./run_sim.sh fw --vcd        # → waveform.vcd

# Gate-level (needs a finished OpenLane run with final/nl/ + final/sdf/)
./run_gls.sh                 # smoke + SDF timing → waveform_gls.vcd
./run_gls.sh fw --vcd        # → waveform_gls.vcd  (use this for power)
./run_gls.sh fw --vcd --no-sdf   # optional: fast zero-delay GLS
```

Then:

```bash
../power/run_power.sh ./waveform_gls.vcd
```

Open `*.vcd` in Cursor with the **Surfer** or **VaporView** extension, or GTKWave.

## Modes

| Mode | What it does | Default VCD (RTL / GLS) |
|------|----------------|-------------------------|
| `smoke` | Tiny hand-loaded program writes `tohost` and halts | `waveform.vcd` / `waveform_gls.vcd` |
| `fw` | Builds firmware (`firmware/`) and runs MNIST MLP until halt | off unless `--vcd` → same names |

PASS for firmware: `tohost = predicted_digit + 1` and SRAM clocks gated.

## Parameters (both scripts)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DUMP_VCD=1` | off for `fw`, on for `smoke` | Write a VCD under `simulation/` |
| `--vcd` / `--no-vcd` | — | CLI flags for firmware mode |
| `VCD_NAME=foo.vcd` | `waveform.vcd` / `waveform_gls.vcd` | Output filename in this folder |
| `TIMEOUT_CYCLES` | `5000000` | Firmware halt timeout (clock cycles) |
| `HARDWARE_TOOLS_ROOT` | `/media/hardware_design_tools` | OSS CAD Suite (`iverilog` / `vvp`) |

### GLS-only

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RUN_DIR` | `synthesis/.../runs/sky130_vex2_soc` | OpenLane run providing `final/nl` + `final/sdf` |
| `STD_CELL_LIBRARY` | from `config.yaml` (else sniffed) | Must match the netlist (`sky130_fd_sc_ms`, `_hd`, …) |
| `SDF_CORNER` | `nom_tt_025C_1v80` | Corner under `final/sdf/` |
| `SDF` | that corner’s `.sdf` | Override SDF path |
| `--no-sdf` / `NO_SDF=1` | off | Zero-delay `FUNCTIONAL` cells (no glitches) |
| `CLK_PERIOD_NS` in `tb_*.v` | `10.0` | Edit the localparam in the testbench (SDF: ≥ hardened period) |
| `DUMP_LEVEL` | `1` | `$dumpvars` depth — `1` = SoC nets only (recommended for power) |
| `PDK_ROOT` | `/media/pdk` | `sky130_fd_sc_hd` Verilog + primitives |

**SDF mode (default):** sky130 **timing** models (`-gspecify -ginterconnect`), `$sdf_annotate` of a sanitized post-PnR SDF (stdcell IOPATHs; INTERCONNECT / TIMINGCHECK / SRAM bit-selects dropped for Icarus). Skewed arrivals produce combinational glitches in the VCD. Set `CLK_PERIOD_NS` in the testbench yourself (must be long enough for the hardened design).

**`--no-sdf`:** `FUNCTIONAL` zero-delay cells (old fast path). Still fine for functional GLS; weaker for power activity.

The synthesized CPU regfile is `$deposit`ed to zero at time 0 (`gen_gls_regfile_init.py`) to match the RTL `$readmemb` of `VexRiscv2.v_toplevel_RegFilePlugin_regFile.bin`.

Build artifacts: `simulation/build/` (RTL), `simulation/build_gls/` (gate; includes `sdf_annotate.log` in SDF mode). Testbenches: `tb_sky130_vex2_soc.v`, `tb_fw_mnist.v`.

## Requirements

- Icarus Verilog (`iverilog`, `vvp`) — see `../setup/`
- For `fw` / `firmware`: RISC-V toolchain under `../tools/riscv-none-elf-gcc` (see `../setup/`)
- For GLS: completed synthesis run + PDK cell Verilog (+ `final/sdf/` unless `--no-sdf`)
