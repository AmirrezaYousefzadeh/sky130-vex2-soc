#!/usr/bin/env python3
"""Summarize OpenLane hardening results as plain text.

Reports:
  - number of cells (stdcells + macros; also breakdown)
  - estimated consumed area (instance area, not die size)
  - critical path delay (clock period − worst setup slack)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_clock_period_ns(config: Path) -> float | None:
    if not config.is_file():
        return None
    data = json.loads(config.read_text())
    period = data.get("CLOCK_PERIOD")
    return float(period) if period is not None else None


def find_metrics(design_dir: Path, run_tag: str | None) -> Path:
    runs = design_dir / "runs"
    if run_tag:
        cand = runs / run_tag / "final" / "metrics.json"
        if cand.is_file():
            return cand
    # newest metrics.json under runs/*/final/
    found = sorted(runs.glob("*/final/metrics.json"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise SystemExit(f"No metrics.json under {runs} (did hardening finish?)")
    return found[-1]


def fmt_um2(v: float) -> str:
    return f"{v:,.2f} µm² ({v / 1e6:.4f} mm²)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design-dir", type=Path, required=True)
    ap.add_argument("--run-tag", default="")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("-o", "--output", type=Path, help="Also write this text file")
    args = ap.parse_args()

    metrics_path = find_metrics(args.design_dir, args.run_tag or None)
    m = json.loads(metrics_path.read_text())
    cfg = args.config or (args.design_dir / "config.json")
    period = load_clock_period_ns(cfg)

    cells_total = m.get("design__instance__count")
    cells_std = m.get("design__instance__count__stdcell")
    cells_macro = m.get("design__instance__count__macros")
    area_inst = m.get("design__instance__area")  # consumed (cells+macros), not die
    area_std = m.get("design__instance__area__stdcell")
    area_macro = m.get("design__instance__area__macros")
    die = m.get("design__die__area")
    core = m.get("design__core__area")

    # Prefer worst (most constrained) setup slack across reported corners
    setup_ws = m.get("timing__setup__ws")
    corner = "aggregate"
    for key, val in m.items():
        if key.startswith("timing__setup__ws__corner:") and isinstance(val, (int, float)):
            if setup_ws is None or val < setup_ws:
                setup_ws = val
                corner = key.split("corner:", 1)[-1]

    lines: list[str] = []
    lines.append("sky130_vex2_soc — hardening results")
    lines.append(f"metrics: {metrics_path}")
    lines.append("")
    lines.append("Cells")
    lines.append(f"  total instances     : {cells_total}")
    lines.append(f"  stdcells            : {cells_std}")
    lines.append(f"  macros              : {cells_macro}")
    lines.append("")
    lines.append("Estimated consumed area (placed instance area, NOT die size)")
    if area_inst is not None:
        lines.append(f"  total instance area : {fmt_um2(float(area_inst))}")
    if area_std is not None:
        lines.append(f"  stdcell area        : {fmt_um2(float(area_std))}")
    if area_macro is not None:
        lines.append(f"  macro area          : {fmt_um2(float(area_macro))}")
    if die is not None:
        lines.append(f"  (die area, ref only): {fmt_um2(float(die))}")
    if core is not None:
        lines.append(f"  (core area, ref)    : {fmt_um2(float(core))}")
    lines.append("")
    lines.append("Timing / critical path")
    if period is not None:
        lines.append(f"  clock period        : {period:g} ns  (from {cfg} CLOCK_PERIOD)")
    if setup_ws is not None and period is not None:
        crit = float(period) - float(setup_ws)
        lines.append(f"  worst setup slack   : {float(setup_ws):.4f} ns  ({corner})")
        lines.append(f"  critical path       : {crit:.4f} ns  (period − worst setup slack)")
        if crit > 0:
            lines.append(f"  implied Fmax        : {1000.0 / crit:.2f} MHz")
    elif setup_ws is not None:
        lines.append(f"  worst setup slack   : {float(setup_ws):.4f} ns  ({corner})")
        lines.append("  critical path       : (set CLOCK_PERIOD in config.json to compute)")
    else:
        lines.append("  (no setup slack metrics found)")

    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)

    out = args.output
    if out is None:
        out = metrics_path.parent / "hardening_results.txt"
    out.write_text(text)
    print(f"(also wrote {out})", file=sys.stderr)


if __name__ == "__main__":
    main()
