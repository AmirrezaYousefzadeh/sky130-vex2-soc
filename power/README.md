# Activity-based power measurement

Estimate average power (and energy per inference) from a **VCD** plus a finished OpenLane run (netlist + SPEF), using OpenSTA `set_power_activity`.

**Prefer a gate-level VCD** from `../simulation/run_gls.sh` — net names match the post-PnR netlist, so toggle rates map cleanly. An RTL VCD still works, but unmatched gate nets fall back to a median activity.

## Quick start

```bash
# 1) Gate-level waveform (recommended)
../simulation/run_gls.sh fw --vcd          # → simulation/mnist_mlp_gls.vcd

# 2) Need a completed synthesis run (netlist + SPEF under runs/.../final/)
# 3) Measure power / energy
./run_power.sh ../simulation/mnist_mlp_gls.vcd
# or: ./run_power.sh   # auto-picks mnist_mlp_gls.vcd if present
```

RTL fallback:

```bash
../simulation/run_sim.sh fw --vcd
./run_power.sh ../simulation/mnist_mlp.vcd
```

Outputs (default `power/out_<vcd_basename>/`):

| File | Contents |
|------|----------|
| `power_energy.txt` | Power (mW) + energy per inference (µJ) |
| `power_activity.rpt` | Full OpenSTA `report_power` |
| `activity.json` | Toggle rates extracted from the VCD |
| `power_by_instance.rpt` | Per-instance power |

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `VCD` / first CLI arg | `simulation/mnist_mlp_gls.vcd` if present, else RTL VCD | Input waveform |
| `RUN_DIR` | `synthesis/.../runs/sky130_vex2_soc_v2` | OpenLane run with `final/nl` and `final/spef` |
| `DESIGN_PERIOD_NS` | `40` | ASIC clock for power (must match `CLOCK_PERIOD` in synthesis config) |
| `OUT` | `power/out_<name>/` | Output directory |
| `SCOPE` | `tb_fw_mnist.u_soc` | VCD hierarchy to sample |
| `PDK_ROOT` | `/media/pdk` | Liberty for stdcells |
| `OPENLANE_ROOT` | `/media/hardware_design_tools/openlane2` | Provides `sta` via nix develop |

## Method (short)

1. `vcd_to_activity.py` counts 0→1 toggles per clock cycle in the VCD.  
2. Rates are applied with OpenSTA `set_power_activity` on the **post-PnR** netlist + SPEF.  
3. `summarize_energy.py` reads total power and computes  
   `energy ≈ P × cycles × DESIGN_PERIOD_NS`.

GLS VCDs from `run_gls.sh` dump **SoC-level nets** (`$dumpvars(1, u_soc)`), which match the flat gate netlist without pulling in every stdcell internal or SRAM `mem[]`.

## Requirements

- Completed synthesis run (`RUN_DIR/final/...`)
- Nix + OpenLane env (see `../setup/`)
- SRAM liberty present under `synthesis/sky130_vex2_soc/macros/`
