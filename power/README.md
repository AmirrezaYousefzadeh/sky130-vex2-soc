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

Checked-in snapshot of the GLS MNIST run: [`../docs/results/power_energy.txt`](../docs/results/power_energy.txt)
(also summarized in `mnist_mlp/SUMMARY.txt` and the root README).

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

## Activity-aware (per-pin) power: `run_pin_power.sh`

The two flows above annotate one global toggle rate plus the SRAM control pins, so their awake power hardly depends on the
workload. `run_pin_power.sh` is the activity-aware flow (ported from the author's `sky130-snn-bmi` repository): every
variable of the `u_soc` scope gets its own measured transition rate and duty, and the clock propagation stops at the
clock-gate outputs, so gated clock trees count what the waveform shows (sleep is then measured, not case-analysed).

```bash
python3 ./vcd_windows.py ../simulation/waveform_gls_mnist.vcd -o windows.json      # awake intervals, idle and decode windows
./run_pin_power.sh ../simulation/waveform_gls_mnist.vcd out_pin_mnist_full                  # whole waveform
./run_pin_power.sh ../simulation/waveform_gls_mnist.vcd out_pin_mnist_decode --begin B --end E   # one window (VCD time units)
python3 ./pin_energy.py --kind mnist --decode out_pin_mnist_decode --idle out_pin_mnist_idle --full out_pin_mnist_full --windows windows.json
```

| piece | role |
|---|---|
| `tools/vcd_toggles.c` | streams the VCD (file of any size), counts transitions and high time per variable with OpenSTA's `read_power_activities` rules, optional `--begin/--end` window |
| `tools/toggles_to_activity.py` | `set_power_activity` for every pin / net / port (nets are annotated through their driver pins) |
| `power_pin_sta.tcl` | netlist + SPEF + liberty (vdd-only SRAM liberty `macros/*_pwr.lib`, so macro energy is not counted twice), `set_clock_sense -stop_propagation` at the clock gates, unannotated inputs at zero, `report_power` by group / instance / macro / clock tree |
| `vcd_windows.py` | awake intervals, longest idle interval, MNIST decode window from `clk`, `sram_clk_en`, `wake`, `gpio_done` |
| `pin_energy.py` | energy per inference (MNIST decode window) or per event / to the decision / per sample (N-MNIST) from the window results and the testbench reports |

Each OpenSTA run takes a few minutes (netlist + SPEF load); the toggle count of a 3 GB waveform takes under a minute.

## Event-driven N-MNIST workload (energy per event, to the decision, per sample)

The N-MNIST firmware wakes once per input event and sleeps in between, so its energy is the per-event awake
energy times the number of events plus the sleep power over the stream. The full stream (about 1,700 events, 100 ms)
is too long for an SDF gate-level VCD, so the flow measures the per-event activity on a shortened stream and
combines it with the full-stream testbench report:

```bash
RUN_DIR=<openlane run> ./measure_nmnist.sh 100        # K = events in the gate-level power run
#  1. simulation/run_sim.sh nmnist            -> docs/results/nmnist_sim.txt (decision latency, awake cycles / event)
#  2. trim_sample.py + run_gls.sh nmnist --vcd (SDF)  on the first K events
#  3. run_avg_power.sh (SCOPE=tb_fw_nmnist.u_soc)     -> docs/results/nmnist_power_energy.txt (P_awake, P_sleep)
#  4. nmnist_energy.py                                 -> docs/results/nmnist_energy.txt
# FULL_GLS=1 adds a zero-delay gate-level run of the whole stream (PASS check on the netlist).
```

`nmnist_energy.py` reports energy per event, energy to the decision (`gpio_done` edge), energy per sample and the
average power at the sample's real-time event rate.

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
