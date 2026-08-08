# Synthesis / OpenLane 2

ASIC implementation flow for `sky130_vex2_soc` on SkyWater 130 nm (sky130A).

## Quick start

```bash
source ../env.sh
./run_synthesis.sh                 # full OpenLane run + text summary
./run_synthesis.sh --report-only   # summarize an existing run
```

Summary is printed to stdout and written next to metrics as `runs/<tag>/final/synthesis_results.txt`.

Reported fields:

- **number of cells** — total / stdcell / macro instance counts  
- **estimated consumed area** — OpenLane `design__instance__area` (cell + macro area), **not** die size  
- **critical path** — `CLOCK_PERIOD − worst setup slack` (ns)

## Where parameters live

| Parameter | File | Key / notes |
|-----------|------|-------------|
| **Clock period (ns)** | `sky130_vex2_soc/config.yaml` | `CLOCK_PERIOD: 40` → 25 MHz |
| IR-drop report | same | `RUN_IRDROP_REPORT: false` — PSM fails on SRAM22 met2 pin islands; re-enable when PDN/PSM is clean |
| Magics GDS streamout | same | `RUN_MAGIC_STREAMOUT: false` — use KLayout; Magics still useful for optional WriteLEF |
| Clock port name | same | `CLOCK_PORT: clk` |
| Die / core box | same | `DIE_AREA`, `CORE_AREA` (floorplan outline, not “consumed” area) |
| Placement density | same | `PL_TARGET_DENSITY_PCT` |
| PDN script | `sky130_vex2_soc/pdn_cfg_sram22.tcl` | referenced by `FP_PDN_CFG` |
| SRAM macro placement | `config.yaml` → `MACROS` | `u_imem` / `u_dmem` locations |
| Macro views (LEF/GDS/LIB) | `sky130_vex2_soc/macros/` | prepared via `scripts/fix_sram22_macro.sh` |

RTL sources are listed under `VERILOG_FILES` in `config.yaml` (paths relative to the design dir).

## Script env overrides

| Env | Default | Meaning |
|-----|---------|---------|
| `RUN_TAG` | `sky130_vex2_soc` | OpenLane run directory name under `sky130_vex2_soc/runs/` |
| `CFG` | `sky130_vex2_soc/config.yaml` | Config YAML path |
| `FROM` / `TO` | empty | Resume / stop at OpenLane step id |
| `OVERWRITE` | `1` | Pass `--overwrite` (disabled automatically with `FROM`) |
| `PDK_ROOT` | `/media/pdk` | sky130 PDK |
| `OPENLANE_ROOT` | `/media/hardware_design_tools/openlane2` | OpenLane 2 checkout |

## Requirements

See `../setup/` for Nix, PDK (volare), and OpenLane install. Macro LEF/GDS must exist under `sky130_vex2_soc/macros/` (run `synthesis/scripts/fix_sram22_macro.sh` after cloning SRAM22).

## Extra helpers

Under `synthesis/scripts/`: floorplan PNG export, area/Fmax explore configs, SRAM22 macro patching.
