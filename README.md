# sky130 VexRiscv + SRAM22 SoC

Open-source path toward a tapeout-oriented RISC-V design on SkyWater 130 nm:
**VexRiscv with a four-stage internal pipeline** + **two SRAM22 macros** for instruction and data memory.

## Locked choices

| Block | Choice | Notes |
|-------|--------|--------|
| Core | `VexRiscv2` (decode/execute/memory/writeback, bypass, mul/div) | Generated from SpinalHDL; timing-oriented for a 60 MHz target |
| IMEM | `sram22_2048x32m8w8` | 2048 × 32 = **8 KiB** |
| DMEM | `sram22_2048x32m8w8` | same |

## Memory map

| Region | Address | Size |
|--------|---------|------|
| IMEM (fetch only) | `0x0000_0000` – `0x0000_1FFF` | 8 KiB |
| DMEM | `0x1000_0000` – `0x1000_1FFF` | 8 KiB |
| tohost | `0x2000_0000` | write nonzero → `halted`, SRAM clocks gated |

## Repository layout

```
setup/          install PDK, Nix, OpenLane, toolchains
rtl/            CPU, SoC bridges, SRAM behavioral link
firmware/       bare-metal MNIST MLP firmware
simulation/     Icarus RTL + gate-level sims + VCD waveforms
synthesis/      OpenLane config + run_synthesis.sh
power/          activity-based power / energy from VCD (prefer GLS)
third_party/    VexRiscv, sram22_sky130_macros (fetch via setup/)
```

## Quick start

```bash
# Tools + PDK (once)
cd setup && ./install_nix.sh && ./install_pdk.sh && ./install_openlane.sh
./install_oss_cad_suite.sh && ./install_riscv_toolchain.sh && ./fetch_third_party.sh
cd ..
source env.sh

# Simulate (RTL)
./simulation/run_sim.sh
./simulation/run_sim.sh fw --vcd

# Synthesis (clock period: synthesis/sky130_vex2_soc/config.yaml → CLOCK_PERIOD)
./synthesis/run_synthesis.sh

# Gate-level sim → VCD for power (SDF delays + glitches; needs final/nl + final/sdf)
./simulation/run_gls.sh fw --vcd

# Power / energy (prefers gate-level VCD when present)
./power/run_power.sh ./simulation/waveform_gls.vcd
```

Each of `setup/`, `simulation/`, `synthesis/`, `power/`, and `firmware/` has its own README with parameters.

## Shared paths

| Path | Purpose |
|------|---------|
| `/media/pdk` | `PDK_ROOT` (sky130A via volare) |
| `/media/hardware_design_tools` | OpenLane, OSS CAD Suite, volare venv |

```bash
source env.sh
```
