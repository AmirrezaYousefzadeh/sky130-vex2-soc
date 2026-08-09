# Power measurement

Two flows share the same VCD + OpenLane netlist/SPEF + OpenSTA activity model.

| Script | What it does |
|--------|----------------|
| `run_avg_power.sh` | One average power / energy number for the whole VCD |
| `run_time_power.sh` | Slice VCD into **N equal time windows**, power per window → **power VCD** |

**Prefer a gate-level VCD** from `../simulation/run_gls.sh` (SDF timing by default). Absolute accuracy is still order-of-magnitude (±30–50%); use for relative / timeline insight, not tapeout signoff.

## Average power (whole run)

```bash
../simulation/run_gls.sh fw --vcd          # → simulation/waveform_gls.vcd
./run_avg_power.sh ../simulation/waveform_gls.vcd
```

Outputs under `power/out_<vcd_basename>/`: `power_energy.txt`, `power_activity.rpt`, `activity.json`, …

## Time-based power (windowed timeline)

```bash
./run_time_power.sh ../simulation/waveform_gls.vcd
./run_time_power.sh ../simulation/waveform_gls.vcd --windows 100
```

Default **N=1000** equal time slots over `[0, t_end]`. Progress bars print for VCD parse and OpenSTA windows.

Outputs under `power/out_<vcd>_time/` (gitignored):

| File | Contents |
|------|----------|
| `power_vs_time.vcd` | Stairstep µW traces for GTKWave / Surfer |
| `power_vs_time.csv` | Same numbers (side-car) |
| `power_time_summary.txt` | avg / peak / window of peak |
| `windows.json` | per-window activity used by STA |

### Timeline figure (clk / sleep / inference / power)

```bash
python3 ./plot_power_timeline.py
# → ../docs/figures/power_timeline.png|.pdf
```

Uses `windows.json` (`sram_clk_en` duty → sleep) and `power_vs_time.csv` (total µW).

### Hierarchy in the power VCD (depth=1)

Post-PnR netlist is flat (CPU dissolved). Depth=1 reports:

| Signal prefix | Meaning |
|---------------|---------|
| `top_*` | whole design |
| `u_imem_*` / `u_dmem_*` | SRAM macros |
| `logic_*` | residual = top − macros |

For each: `total_uW` and `static_uW` (OpenSTA **Leakage**). `--depth` is accepted; only `1` is implemented today.

### Time-power parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `VCD` / first arg | `waveform_gls.vcd` if present | Input waveform |
| `--windows` / `WINDOWS` | `1000` | Equal time slots |
| `--depth` / `DEPTH` | `1` | Hierarchy depth (only 1 for now) |
| `RUN_DIR` | `synthesis/.../runs/sky130_vex2_soc` | Netlist + SPEF |
| `DESIGN_PERIOD_NS` | `CLOCK_PERIOD` from config | ASIC clock for power |
| `OUT` | `power/out_<name>_time/` | Output directory |
| `SCOPE` | `tb_fw_mnist.u_soc` | VCD hierarchy to sample |

## Method (short)

1. Count 0→1 toggles (and duty) in the VCD — globally or per time window.  
2. Apply rates with OpenSTA `set_power_activity` on post-PnR netlist + SPEF.  
3. Clock tree: `create_clock` + `set_propagated_clock` (not VCD activity on `clk`).  
4. **Sleep / clock gate:** OpenSTA ignores `set_power_activity` on ICG `GATE` for power.
   The flow case-analyzes the core `dlclkp` GATE from VCD `sram_clk_en` duty
   (`power_icg_utils.tcl`): sleep windows → GATE=0 (core_clk off); awake → GATE=1.
   Average power blends `duty·P_awake + (1−duty)·P_sleep`.  
5. Average flow: `energy ≈ P × cycles × DESIGN_PERIOD_NS`.  
6. Time flow: one STA design load, then N `report_power` passes → power VCD.

## Limitations

See the longer notes historically kept for activity-based OpenSTA: median fallback on unmatched nets, sanitized SDF GLS (no INTERCONNECT), TT liberty corner, workload-specific. Time-based peaks are **hottest window averages**, not sub-window instantaneous current. Always-on `clk` (sleep FSM) still contributes a small residual in sleep.

## Requirements

- Completed synthesis run (`RUN_DIR/final/...`)
- Nix + OpenLane env (see `../setup/`)
- SRAM liberty under `synthesis/sky130_vex2_soc/macros/`
