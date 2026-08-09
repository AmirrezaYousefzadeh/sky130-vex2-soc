#!/usr/bin/env python3
"""Summarize OpenLane synthesis results as plain text.

Reports:
  - number of cells (stdcells + macros; also breakdown)
  - estimated consumed area (instance area, not die size)
  - critical path delay (clock period − worst setup slack)
  - clear MET / VIOLATED status for setup and hold vs CLOCK_PERIOD
"""
from __future__ import annotations

import argparse
import json
import os
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


def run_dir_for(metrics_path: Path) -> Path:
    """OpenLane run directory that contains final/ or step folders."""
    p = metrics_path.parent
    if p.name == "final":
        return p.parent
    # .../NN-openroad-stapostpnr/metrics.json
    if p.parent.name == "runs" or (p.parent / "resolved.json").is_file():
        return p.parent
    for _ in range(4):
        if (p / "resolved.json").is_file() or (p / "final").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return metrics_path.parent


def fmt_um2(v: float) -> str:
    return f"{v:,.2f} µm² ({v / 1e6:.4f} mm²)"


def worst_slack(m: dict, prefix: str) -> tuple[float | None, str]:
    """Return (worst slack, corner label). Prefer aggregate key; else min over corners."""
    setup_ws = m.get(prefix)
    corner = "aggregate"
    for key, val in m.items():
        if key.startswith(prefix + "__corner:") and isinstance(val, (int, float)):
            if setup_ws is None or val < float(setup_ws):
                setup_ws = val
                corner = key.split("corner:", 1)[-1]
    if isinstance(setup_ws, (int, float)):
        return float(setup_ws), corner
    return None, corner


def verdict(slack: float | None, vio_count: object) -> str:
    n = int(vio_count) if isinstance(vio_count, (int, float)) else None
    if slack is None:
        return "UNKNOWN"
    if slack < 0 or (n is not None and n > 0):
        return "VIOLATED"
    return "MET"


def detect_scl_from_netlist(run_dir: Path) -> str | None:
    """Return actual mapped stdcell family from netlist (e.g. sky130_fd_sc_hs)."""
    import re
    from collections import Counter

    candidates = [
        run_dir / "final" / "nl" / "sky130_vex2_soc.nl.v",
        *sorted(run_dir.glob("*-yosys-synthesis/*.nl.v")),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        counts: Counter[str] = Counter()
        with path.open(errors="replace") as f:
            for line in f:
                for m in re.finditer(r"sky130_fd_sc_[a-z]+", line):
                    counts[m.group(0)] += 1
        if counts:
            return counts.most_common(1)[0][0]
    return None


def colorize_report(text: str, *, use_color: bool) -> str:
    """Highlight VIOLATED / FAIL / WARNING lines in red when printing to a TTY."""
    if not use_color:
        return text
    red = "\033[1;31m"
    reset = "\033[0m"
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if any(tok in line for tok in ("VIOLATED", "FAIL", "WARNING")):
            # Preserve trailing newline outside the color span.
            body = line.rstrip("\n")
            nl = line[len(body) :]
            out.append(f"{red}{body}{reset}{nl}")
        else:
            out.append(line)
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design-dir", type=Path, required=True)
    ap.add_argument("--run-tag", default="")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        action="append",
        default=None,
        help="Write report here (repeatable). Defaults: run dir + final/ + design dir.",
    )
    args = ap.parse_args()

    metrics_path = find_metrics(args.design_dir, args.run_tag or None)
    m = load_metrics_dict(metrics_path)
    cfg = args.config or (args.design_dir / "config.yaml")
    if not args.config and not cfg.is_file():
        cfg = args.design_dir / "config.json"
    period = load_clock_period_ns(cfg, metrics_path)
    run_dir = run_dir_for(metrics_path)

    # Config may claim HS while netlist is still HD — report what was actually mapped.
    scl_claimed = None
    resolved = run_dir / "resolved.json"
    if resolved.is_file():
        try:
            rd = json.loads(resolved.read_text())
            scl_claimed = rd.get("STD_CELL_LIBRARY")
        except (OSError, json.JSONDecodeError):
            pass
    scl_actual = detect_scl_from_netlist(run_dir)

    cells_total = m.get("design__instance__count")
    cells_std = m.get("design__instance__count__stdcell")
    cells_macro = m.get("design__instance__count__macros")
    area_inst = m.get("design__instance__area")  # consumed (cells+macros), not die
    area_std = m.get("design__instance__area__stdcell")
    area_macro = m.get("design__instance__area__macros")
    die = m.get("design__die__area")
    core = m.get("design__core__area")

    setup_ws, setup_corner = worst_slack(m, "timing__setup__ws")
    hold_ws, hold_corner = worst_slack(m, "timing__hold__ws")
    setup_vio = m.get("timing__setup_vio__count", m.get("timing__setup_r2r_vio__count"))
    hold_vio = m.get("timing__hold_vio__count", m.get("timing__hold_r2r_vio__count"))
    setup_status = verdict(setup_ws, setup_vio)
    hold_status = verdict(hold_ws, hold_vio)

    lines: list[str] = []
    lines.append("sky130_vex2_soc — synthesis results")
    lines.append(f"metrics: {metrics_path}")
    lines.append(f"run:     {run_dir}")
    if scl_actual:
        lines.append(f"stdcells (netlist): {scl_actual}")
        if scl_claimed and scl_claimed != scl_actual:
            lines.append(
                f"WARNING: config claimed {scl_claimed} but netlist is {scl_actual}"
            )
    elif scl_claimed:
        lines.append(f"stdcells (config):  {scl_claimed}")
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
    lines.append("Timing constraints (clock)")
    if period is not None:
        lines.append(f"  clock period        : {period:.3f} ns  ({1000.0 / period:.2f} MHz target)")
    else:
        lines.append("  clock period        : n/a")

    if setup_ws is not None and period is not None:
        crit = period - setup_ws
        sign = "+" if setup_ws >= 0 else ""
        lines.append(
            f"  setup slack (WNS)   : {sign}{setup_ws:.4f} ns  ({setup_corner})  → {setup_status}"
        )
        if isinstance(setup_vio, (int, float)):
            lines.append(f"  setup violations    : {int(setup_vio)}")
        lines.append(f"  critical path       : {crit:.4f} ns")
        if crit > 0:
            lines.append(f"  implied Fmax (path) : {1000.0 / crit:.2f} MHz")
    else:
        lines.append("  setup               : n/a (need CLOCK_PERIOD + timing__setup__ws*)")
        setup_status = "UNKNOWN"

    if hold_ws is not None:
        sign = "+" if hold_ws >= 0 else ""
        lines.append(
            f"  hold slack (WNS)    : {sign}{hold_ws:.4f} ns  ({hold_corner})  → {hold_status}"
        )
        if isinstance(hold_vio, (int, float)):
            lines.append(f"  hold violations     : {int(hold_vio)}")
    else:
        lines.append("  hold                : n/a")
        hold_status = "UNKNOWN"

    lines.append("")
    if setup_status == "MET" and hold_status in {"MET", "UNKNOWN"}:
        overall = "PASS — clock setup/hold constraints MET"
    elif setup_status == "VIOLATED" or hold_status == "VIOLATED":
        overall = "FAIL — timing VIOLATIONS (see setup/hold above)"
    else:
        overall = "UNKNOWN — incomplete timing metrics"
    lines.append(f"RESULT: {overall}")
    lines.append("")
    lines.append("Notes")
    lines.append("  Setup MET  ⇒ critical path fits in CLOCK_PERIOD (positive slack).")
    lines.append("  Hold MET   ⇒ no hold-time failures after CTS/PnR.")
    lines.append("  Slack < 0 or violation count > 0 ⇒ constraint not met.")
    lines.append("")

    text = "\n".join(lines) + "\n"

    outputs: list[Path] = []
    if args.output:
        outputs.extend(args.output)
    else:
        outputs.append(run_dir / "synthesis_results.txt")
        if (run_dir / "final").is_dir():
            outputs.append(run_dir / "final" / "synthesis_results.txt")
        outputs.append(args.design_dir / "synthesis_results.txt")

    for out in outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"Wrote report: {out}", file=sys.stderr)

    # Colored report last on stdout so nothing follows it in the terminal.
    use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    sys.stdout.write(colorize_report(text, use_color=use_color))


if __name__ == "__main__":
    main()
