# Activity-based power measurement

Estimate average power (and energy per inference) from an RTL **VCD** plus a finished OpenLane run (netlist + SPEF), using OpenSTA `set_power_activity`.

## Quick start

```bash
# 1) Capture a waveform
../simulation/run_sim.sh fw --vcd          # → simulation/mnist_mlp.vcd

# 2) Need a completed harden run (netlist + SPEF under runs/.../final/)
# 3) Measure power / energy
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
| `VCD` / first CLI arg | `simulation/mnist_mlp.vcd` | Input waveform |
| `RUN_DIR` | `hardening/.../runs/sky130_vex2_soc_v2` | OpenLane run with `final/nl` and `final/spef` |
| `DESIGN_PERIOD_NS` | `40` | ASIC clock for power (must match `CLOCK_PERIOD` in hardening config) |
| `OUT` | `power/out_<name>/` | Output directory |
| `SCOPE` | `tb_fw_mnist.u_soc` | VCD hierarchy to sample |
| `PDK_ROOT` | `/media/pdk` | Liberty for stdcells |
| `OPENLANE_ROOT` | `/media/hardware_design_tools/openlane2` | Provides `sta` via nix develop |

## Method (short)

1. `vcd_to_activity.py` counts 0→1 toggles per clock cycle in the RTL VCD.  
2. Rates are applied with OpenSTA `set_power_activity` on the **post-PnR** netlist + SPEF.  
3. `summarize_energy.py` reads total power and computes  
   `energy ≈ P × cycles × DESIGN_PERIOD_NS`.

Caveat: the VCD is RTL-level; unmatched gate nets use a median activity. For higher accuracy, use a gate-level VCD.

## Requirements

- Completed hardening run (`RUN_DIR/final/...`)
- Nix + OpenLane env (see `../setup/`)
- SRAM liberty present under `hardening/sky130_vex2_soc/macros/`
