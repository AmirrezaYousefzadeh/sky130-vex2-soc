# Hardening (OpenLane 2)

ASIC implementation flow for `sky130_vex2_soc` on SkyWater 130 nm (sky130A).

## Quick start

```bash
source ../env.sh
./run_harden.sh                 # full OpenLane run + text summary
./run_harden.sh --report-only   # summarize an existing run
```

Summary is printed to stdout and written next to metrics as `runs/<tag>/final/hardening_results.txt`.

Reported fields:

- **number of cells** — total / stdcell / macro instance counts  
- **estimated consumed area** — OpenLane `design__instance__area` (cell + macro area), **not** die size  
- **critical path** — `CLOCK_PERIOD − worst setup slack` (ns)

## Where parameters live

| Parameter | File | Key / notes |
|-----------|------|-------------|
| **Clock period (ns)** | `sky130_vex2_soc/config.json` | `"CLOCK_PERIOD": 40` → 25 MHz |
| Clock port name | same | `"CLOCK_PORT": "clk"` |
| Die / core box | same | `DIE_AREA`, `CORE_AREA` (floorplan outline, not “consumed” area) |
| Placement density | same | `PL_TARGET_DENSITY_PCT` |
| PDN script | `sky130_vex2_soc/pdn_cfg_sram22.tcl` | referenced by `FP_PDN_CFG` |
| SRAM macro placement | `config.json` → `MACROS` | `u_imem` / `u_dmem` locations |
| Macro views (LEF/GDS/LIB) | `sky130_vex2_soc/macros/` | prepared via `scripts/fix_sram22_macro.sh` |

RTL sources are listed under `VERILOG_FILES` in `config.json` (paths relative to the design dir).

## Script env overrides

| Env | Default | Meaning |
|-----|---------|---------|
| `RUN_TAG` | `sky130_vex2_soc` | OpenLane run directory name under `sky130_vex2_soc/runs/` |
| `CFG` | `sky130_vex2_soc/config.json` | Config JSON path |
| `FROM` / `TO` | empty | Resume / stop at OpenLane step id |
| `OVERWRITE` | `1` | Pass `--overwrite` (disabled automatically with `FROM`) |
| `PDK_ROOT` | `/media/pdk` | sky130 PDK |
| `OPENLANE_ROOT` | `/media/hardware_design_tools/openlane2` | OpenLane 2 checkout |

## Requirements

See `../setup/` for Nix, PDK (volare), and OpenLane install. Macro LEF/GDS must exist under `sky130_vex2_soc/macros/` (run `hardening/scripts/fix_sram22_macro.sh` after cloning SRAM22).

## Extra helpers

Under `hardening/scripts/`: floorplan PNG export, area/Fmax explore configs, SRAM22 macro patching.
