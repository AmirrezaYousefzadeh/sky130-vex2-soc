#!/usr/bin/env python3
"""Summarize OpenLane synthesis results as plain text.

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


def period_from_sdc(metrics_path: Path) -> float | None:
    import re

    run_root = metrics_path.parent
    # state_out is under *-stapostpnr/; climb to the OpenLane run directory
    for _ in range(4):
        if (run_root / "resolved.json").is_file() or list(run_root.glob("*-yosys-synthesis")):
            break
        if run_root.parent == run_root:
            break
        run_root = run_root.parent

    candidates: list[Path] = []
    candidates.extend(metrics_path.parent.glob("*.sdc"))
    candidates.extend(run_root.glob("*-openroad-fillinsertion/*.sdc"))
    candidates.extend(run_root.glob("*-openroad-stapostpnr/*.sdc"))
    for sdc in candidates:
        try:
            text = sdc.read_text()
        except OSError:
            continue
        m = re.search(r"create_clock\s+.*?-period\s+([0-9.]+)", text, re.S)
        if m:
            return float(m.group(1))
    # clock.rpt "Period: 40.000000"
    for rpt in metrics_path.parent.rglob("clock.rpt"):
        m = re.search(r"Period:\s*([0-9.]+)", rpt.read_text())
        if m:
            return float(m.group(1))
    return None


def load_clock_period_ns(config: Path, metrics_path: Path | None = None) -> float | None:
    if metrics_path is not None:
        p = period_from_sdc(metrics_path)
        if p is not None:
            return p
    if not config.is_file():
        return None
    text = config.read_text()
    if config.suffix in {".yml", ".yaml"}:
        try:
            import yaml

            data = yaml.safe_load(text)
        except ImportError:
            import re

            m = re.search(r"(?m)^CLOCK_PERIOD:\s*([0-9.]+)\s*$", text)
            return float(m.group(1)) if m else None
        if not isinstance(data, dict):
            return None
        period = data.get("CLOCK_PERIOD")
        return float(period) if period is not None else None
    data = json.loads(text)
    period = data.get("CLOCK_PERIOD")
    return float(period) if period is not None else None


def load_metrics_dict(path: Path) -> dict:
    data = json.loads(path.read_text())
    if "metrics" in data and isinstance(data["metrics"], dict):
        return data["metrics"]
    return data


def find_metrics(design_dir: Path, run_tag: str | None) -> Path:
    runs = design_dir / "runs"
    ordered: list[Path] = []
    if run_tag:
        tagged = runs / run_tag
        ordered.append(tagged / "final" / "metrics.json")
        ordered.extend(
            sorted(
                tagged.glob("*-openroad-stapostpnr/metrics.json"),
                key=lambda p: p.stat().st_mtime,
            )
        )
        ordered.extend(
            sorted(
                tagged.glob("*-openroad-stapostpnr/state_out.json"),
                key=lambda p: p.stat().st_mtime,
            )
        )
        for cand in ordered:
            if cand.is_file():
                return cand
        raise SystemExit(
            f"No metrics for run tag '{run_tag}' under {tagged} "
            f"(need final/metrics.json or *-openroad-stapostpnr/state_out.json)"
        )
    ordered.extend(sorted(runs.glob("*/final/metrics.json"), key=lambda p: p.stat().st_mtime))
    ordered.extend(
        sorted(runs.glob("*/**-openroad-stapostpnr/state_out.json"), key=lambda p: p.stat().st_mtime)
    )
    for cand in ordered:
        if cand.is_file():
            return cand
    raise SystemExit(f"No metrics.json / STA state under {runs} (did synthesis finish STA?)")


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
    m = load_metrics_dict(metrics_path)
    cfg = args.config or (args.design_dir / "config.yaml")
    if not args.config and not cfg.is_file():
        cfg = args.design_dir / "config.json"
    period = load_clock_period_ns(cfg, metrics_path)

    cells_total = m.get("design__instance__count")
    cells_std = m.get("design__instance__count__stdcell")
    cells_macro = m.get("design__instance__count__macros")
    area_inst = m.get("design__instance__area")  # consumed (cells+macros), not die
    area_std = m.get("design__instance__area__stdcell")
    area_macro = m.get("design__instance__area__macros")
    die = m.get("design__die__area")
    core = m.get("design__core__area")

    setup_ws = m.get("timing__setup__ws")
    corner = "aggregate"
    for key, val in m.items():
        if key.startswith("timing__setup__ws__corner:") and isinstance(val, (int, float)):
            if setup_ws is None or val < setup_ws:
                setup_ws = val
                corner = key.split("corner:", 1)[-1]

    lines: list[str] = []
    lines.append("sky130_vex2_soc — synthesis results")
    lines.append(f"metrics: {metrics_path}")
    lines.append("")
    lines.append("Cells")
    lines.append(f"  total instances     : {cells_total}")
    lines.append(f"  stdcells            : {cells_std}")
    lines.append(f"  macros              : {cells_macro}")
    lines.append("")
    lines.append("Estimated consumed area (instance area)")
    if isinstance(area_inst, (int, float)):
        lines.append(f"  total               : {fmt_um2(float(area_inst))}")
    else:
        lines.append("  total               : n/a")
    if isinstance(area_std, (int, float)):
        lines.append(f"  stdcells            : {fmt_um2(float(area_std))}")
    if isinstance(area_macro, (int, float)):
        lines.append(f"  macros              : {fmt_um2(float(area_macro))}")
    if isinstance(die, (int, float)):
        lines.append(f"  die outline (ref)   : {fmt_um2(float(die))}")
    if isinstance(core, (int, float)):
        lines.append(f"  core outline (ref)  : {fmt_um2(float(core))}")
    lines.append("")
    lines.append("Critical path")
    if period is not None and isinstance(setup_ws, (int, float)):
        crit = period - float(setup_ws)
        lines.append(f"  clock period        : {period:.3f} ns")
        lines.append(f"  worst setup slack   : {float(setup_ws):.4f} ns  ({corner})")
        lines.append(f"  critical path       : {crit:.4f} ns")
        if period > 0:
            lines.append(f"  implied Fmax (ws)   : {1000.0 / period:.2f} MHz (constraint)")
            # period_min style if slack>=0: fmax ~= 1000/(period-ws) when ws>0? 
            # Actually critical path delay = period - ws; fmax = 1000/crit
            if crit > 0:
                lines.append(f"  implied Fmax (path) : {1000.0 / crit:.2f} MHz")
    else:
        lines.append("  n/a (need CLOCK_PERIOD + timing__setup__ws*)")
    lines.append("")

    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)

    out = args.output
    if out is None and metrics_path.parent.name == "final":
        out = metrics_path.parent / "synthesis_results.txt"
    elif out is None:
        out = metrics_path.parent / "synthesis_results.txt"
    out.write_text(text)


if __name__ == "__main__":
    main()
