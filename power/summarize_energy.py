#!/usr/bin/env python3
"""Build a compact power + energy text report from activity JSON + OpenSTA power rpt."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_total_watts(rpt: Path) -> float | None:
    """Best-effort parse of OpenSTA report_power total."""
    text = rpt.read_text(errors="replace")
    # Common patterns: "Total" line with watts in last numeric column
    for line in text.splitlines():
        if re.search(r"\bTotal\b", line, re.I) and re.search(r"\d", line):
            nums = re.findall(r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?|\d+", line)
            if nums:
                # OpenSTA often prints Internal Switching Leakage Total
                try:
                    return float(nums[-1])
                except ValueError:
                    continue
    # Fallback: look for "Total Power"
    m = re.search(r"Total\s+Power\s*[:=]?\s*([0-9.eE+-]+)", text, re.I)
    if m:
        return float(m.group(1))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--activity-json", type=Path, required=True)
    ap.add_argument("--power-rpt", type=Path, required=True)
    ap.add_argument("--design-period-ns", type=float, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    act = json.loads(args.activity_json.read_text())
    cycles = int(act.get("cycles") or 0)
    sim_period_ns = float(act.get("sim_period_ns") or 10.0)
    median = float(act.get("global_activity_median") or 0.0)
    interesting = act.get("interesting") or {}

    p_w = parse_total_watts(args.power_rpt)
    design_period_ns = float(args.design_period_ns)
    f_hz = 1e9 / design_period_ns if design_period_ns else 0.0

    lines: list[str] = []
    lines.append("Activity-based power / energy summary")
    lines.append(f"vcd                 : {act.get('vcd')}")
    lines.append(f"cycles              : {cycles}")
    lines.append(f"vcd_sim_clock       : {1e3 / sim_period_ns:.4g} MHz ({sim_period_ns:g} ns TB period)")
    lines.append(f"design_clock        : {f_hz / 1e6:.4g} MHz ({design_period_ns:g} ns)")
    lines.append(f"activity_median     : {median:.6f} / cycle")
    for k, v in interesting.items():
        if isinstance(v, dict) and "activity" in v:
            lines.append(f"  {k:18s}: {v['activity']:.6f}")
    lines.append("")

    if p_w is None:
        lines.append("power_total         : (could not parse OpenSTA report)")
        lines.append(f"see                  : {args.power_rpt}")
    else:
        p_mw = p_w * 1e3
        lines.append(f"power_total         : {p_mw:.6f} mW  ({p_w:.6e} W)")
        # Energy for one inference ≈ P * (cycles * design_period)
        if cycles > 0 and design_period_ns > 0:
            t_s = cycles * design_period_ns * 1e-9
            e_j = p_w * t_s
            lines.append(f"runtime_one_infer   : {t_s * 1e3:.6f} ms")
            lines.append(f"energy_one_infer    : {e_j * 1e6:.6f} µJ  ({e_j:.6e} J)")
            lines.append("")
            lines.append("Note: energy ≈ P_avg × (cycles × design_period).")
            lines.append("RTL VCD activity annotated onto post-PnR netlist+SPEF (TT 1.8 V).")

    args.output.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
