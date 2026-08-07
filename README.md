# sky130 Vex-2 + SRAM22 SoC

Open-source path toward a tapeout-oriented RISC-V design on SkyWater 130 nm:
**VexRiscv 2-stage (Vex-2)** + **two SRAM22 macros** for instruction and data memory.

## Locked choices

| Block | Choice | Notes |
|-------|--------|--------|
| Core | `VexRiscv2` (2-stage, bypass, mul/div) | Generated from SpinalHDL; low CPI / EPI oriented |
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
fw/             bare-metal MNIST MLP firmware
simulation/     Icarus sims + VCD waveforms
hardening/      OpenLane config + run_harden.sh
power/          activity-based power / energy from VCD
third_party/    VexRiscv, sram22_sky130_macros (fetch via setup/)
```

## Quick start

```bash
# Tools + PDK (once)
cd setup && ./install_nix.sh && ./install_pdk.sh && ./install_openlane.sh
./install_oss_cad_suite.sh && ./install_riscv_toolchain.sh && ./fetch_third_party.sh
cd ..
source env.sh

# Simulate
./simulation/run_sim.sh
./simulation/run_sim.sh fw --vcd

# Harden (clock period: hardening/sky130_vex2_soc/config.json → CLOCK_PERIOD)
./hardening/run_harden.sh

# Power / energy from a VCD
./power/run_power.sh ./simulation/mnist_mlp.vcd
```

Each of `setup/`, `simulation/`, `hardening/`, `power/`, and `fw/` has its own README with parameters.

## Shared paths

| Path | Purpose |
|------|---------|
| `/media/pdk` | `PDK_ROOT` (sky130A via volare) |
| `/media/hardware_design_tools` | OpenLane, OSS CAD Suite, volare venv |

```bash
source env.sh
```
