# Activity-based power measurement

Estimate average power (and energy per inference) from a **VCD** plus a finished OpenLane run (netlist + SPEF), using OpenSTA `set_power_activity`.

**Prefer a gate-level VCD** from `../simulation/run_gls.sh` (SDF timing by default, so stdcell-delay glitches are included — see **Limitations**) — net names match the post-PnR netlist, so toggle rates map cleanly. An RTL VCD still works, but unmatched gate nets fall back to a median activity.

## Quick start

```bash
# 1) Gate-level waveform (recommended)
../simulation/run_gls.sh fw --vcd          # → simulation/waveform_gls.vcd

# 2) Need a completed synthesis run (netlist + SPEF under runs/.../final/)
# 3) Measure power / energy
./run_power.sh ../simulation/waveform_gls.vcd
# or: ./run_power.sh   # auto-picks waveform_gls.vcd if present
```

RTL fallback:

```bash
../simulation/run_sim.sh fw --vcd
./run_power.sh ../simulation/waveform.vcd
```

Outputs (default `power/out_<vcd_basename>/`):

| File | Contents |
|------|----------|
| `power_energy.txt` | Power (mW) + energy; includes **Clock** group breakdown |
| `power_activity.rpt` | Full OpenSTA `report_power` |
| `power_clock_tree.rpt` | Power of named CTS cells (`*clkbuf*`, …) |
| `activity.json` | Toggle rates extracted from the VCD |
| `power_by_instance.rpt` | Per-instance power |

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `VCD` / first CLI arg | `simulation/waveform_gls.vcd` if present, else `waveform.vcd` | Input waveform |
| `RUN_DIR` | `synthesis/.../runs/sky130_vex2_soc` | OpenLane run with `final/nl` and `final/spef` |
| `DESIGN_PERIOD_NS` | `CLOCK_PERIOD` from `config.yaml` | ASIC clock for power (must match hardened period) |
| `STD_CELL_LIBRARY` | from `config.yaml` | Liberty must match the netlist (`sky130_fd_sc_ms`, …) |
| `OUT` | `power/out_<name>/` | Output directory |
| `SCOPE` | `tb_fw_mnist.u_soc` | VCD hierarchy to sample |
| `PDK_ROOT` | `/media/pdk` | Liberty for stdcells |
| `OPENLANE_ROOT` | `/media/hardware_design_tools/openlane2` | Provides `sta` via nix develop |

## Method (short)

1. `vcd_to_activity.py` counts 0→1 toggles per clock cycle in the VCD (data path).  
2. Rates are applied with OpenSTA `set_power_activity` on the **post-PnR** netlist + SPEF.  
3. **Clock tree:** `create_clock` + `set_propagated_clock` (OpenSTA forbids activity on clock ports; clock-network activity is `2/period`). Matching liberty + period are required.  
4. `summarize_energy.py` reads total / group power and computes  
   `energy ≈ P × cycles × DESIGN_PERIOD_NS`.

GLS VCDs from `run_gls.sh` dump **SoC-level nets** (`$dumpvars(1, u_soc)`), which match the flat gate netlist without pulling in every stdcell internal or SRAM `mem[]`.

## Limitations (read this)

This flow is a **relative / order-of-magnitude** power estimate, not silicon-accurate signoff. Absolute numbers are often only good to roughly **±30–50%** (sometimes worse), depending on VCD quality and activity coverage. Use it to compare workloads, configs, or RTL vs GLS trends — not to quote milliwatts as tapeout truth.

### 1. Activity-based OpenSTA, not time-based power

| Limitation | Implication |
|------------|-------------|
| Power comes from **toggle rates** + liberty models (`set_power_activity`), not integrating instantaneous current over the VCD | Glitch *energy* and short pulse shapes are not modeled in OpenSTA; only the *extra toggles* they create in the VCD help. |
| Only a few pins get measured rates; most nets get a **global median** activity | Quiet and hot nets are averaged toward the middle → underestimates busy logic, overestimates idle logic. |
| Macro / SRAM internal activity is coarse | Memory array power may be off; only ports that appear in the VCD (and get rates) help. |
| `energy ≈ P_avg × cycles × period` | Assumes steady average power over the window; startup/reset and early halt skew the average if you include them carelessly. |

### 2. GLS SDF is Icarus-sanitized (not full post-PnR timing)

`../simulation/run_gls.sh` (SDF default) runs `sdf_sanitize_for_icarus.py` so annotation does not abort. That is a **deliberate compromise**:

| What is dropped / changed | Implication for the VCD (and thus power) |
|---------------------------|------------------------------------------|
| All **INTERCONNECT** delays | No wire RC delay or routing skew. Arrival times are cell-delay-only → **fewer / different glitches** than real silicon or a commercial SDF GLS. |
| All **TIMINGCHECK** | Sim will not flag setup/hold fails; a “PASS” GLS does not prove timing closure (use STA reports for that). |
| **COND** IOPATHs unwrapped to plain IOPATH | Conditional arcs always apply → some paths get delay when they would be gated off → activity can be slightly pessimistic or shifted. |
| SRAM **`dout[N]` IOPATHs** | Macro read data is not SDF-delayed; behavioral SRAM timing dominates. Memory-side glitch/skew into the CPU is understated. |
| Simulator is **Icarus**, not VCS/Xcelium/Questa | Even with sanitizing, delay annotation is incomplete vs a full industrial GLS. |

**Net effect:** SDF GLS is still **much better for power activity than zero-delay `--no-sdf`**, because stdcell IOPATH skew produces real combinational glitches in the VCD. It is **not** equivalent to full INTERCONNECT + macro SDF.

### 3. Clock-tree power is modeled, not measured from VCD toggles

OpenSTA forbids `set_power_activity` on clock ports. Clock network power uses `create_clock` + `set_propagated_clock` (activity density `2/period`) and matching liberty.

| Limitation | Implication |
|------------|-------------|
| Clock activity is **assumed ideal** (toggling every cycle), not taken from the VCD | Gated / skewed / duty-cycled clocks in the waveform are not reflected in clock-group power. |
| Period must match the hardened `CLOCK_PERIOD` | Wrong `DESIGN_PERIOD_NS` scales both dynamic power and energy incorrectly. |
| Liberty must match the stdcell library used in PnR | Wrong library → wrong clock-buffer / cell energy tables. |

### 4. Waveform scope and RTL vs GLS

| Limitation | Implication |
|------------|-------------|
| Default dump is `$dumpvars(1, u_soc)` | SoC ports/nets only — good name match to the flat netlist; **no** stdcell internal nodes. Fine for activity on design nets; you do not see inside cells. |
| **RTL VCD** name mismatch | Many gate nets get median fallback → poorer absolute and relative accuracy. Prefer `waveform_gls.vcd`. |
| `--no-sdf` / FUNCTIONAL GLS | Zero-delay cells → almost no combo glitches → **underestimates** dynamic power vs SDF GLS. |

### 5. Corner and workload

Power is for the **liberty / SPEF corner** loaded in OpenSTA (typically the run’s annotated SPEF + chosen stdcell liberty), not a multi-corner envelope. Results are for **this MNIST (or smoke) workload window** only — not a datasheet max power.

## Requirements

- Completed synthesis run (`RUN_DIR/final/...`)
- Nix + OpenLane env (see `../setup/`)
- SRAM liberty present under `synthesis/sky130_vex2_soc/macros/`
