# Last hardened result (reference)

Regenerate after a run with `./synthesis/run_synthesis.sh` (writes local
`synthesis_results.txt`, gitignored). Snapshot below matches the checked-in
`config.yaml` intent for the `sky130_vex2_soc` design point.

| Item | Value |
|------|--------|
| Stdcell library | `sky130_fd_sc_ms` |
| Clock period | 20.0 ns (50 MHz target) |
| Setup / hold | MET (after hold fix) |
| Implied Fmax (critical path) | ~60 MHz |
| Macros | 2 × `sram22_2048x32m8w8` |

SDC: [`sky130_vex2_soc.sdc`](sky130_vex2_soc.sdc). Full OpenLane `runs/` stay local.
