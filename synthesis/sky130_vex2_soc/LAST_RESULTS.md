# Last hardened result (reference)

Regenerate after a run with `./synthesis/run_synthesis.sh` (writes local
`synthesis_results.txt`, gitignored). Snapshot below matches the checked-in
`docs/results/area_timing.txt` for the `sky130_vex2_soc` design point.

| Item | Value |
|------|--------|
| Stdcell library | `sky130_fd_sc_ms` |
| Clock period | 20.0 ns (50 MHz target) |
| Setup WNS / hold WNS | +1.125 ns / +0.048 ns — **MET** |
| Critical path / implied Fmax | 18.875 ns / **53.0 MHz** |
| Macros | 2 × `sram22_2048x32m8w8` |
| Consumed area (total) | **1.422 mm²** (cells 0.367 + macros 1.055) |
| Die / core outline | 4.000 / 3.831 mm² (floorplan box, not utilization) |
| Instances | 63 776 (63 774 stdcells + 2 macros) |

Consumed area is OpenLane `design__instance__area`, not die size.

SDC: [`sky130_vex2_soc.sdc`](sky130_vex2_soc.sdc). Full OpenLane `runs/` stay local.
