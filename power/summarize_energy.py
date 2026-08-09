#!/usr/bin/env python3
"""Build a compact power + energy text report from activity JSON + OpenSTA power rpt."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _nums(line: str) -> list[float]:
    return [float(x) for x in re.findall(r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?|\d+", line)]


def parse_group_watts(rpt: Path) -> dict[str, float]:
    """Parse OpenSTA report_power group rows → {group: total_watts}.

    Typical columns: Group Internal Switching Leakage Total  (%)
    """
    text = rpt.read_text(errors="replace")
    out: dict[str, float] = {}
    row_re = re.compile(
        r"^\s*(Sequential|Combinational|Clock|Macro|Pad|Total)\s+(.*)$",
        re.I | re.M,
    )
    for m in row_re.finditer(text):
        name = m.group(1)
        group = "Total" if name.lower() == "total" else name.title()
        nums = _nums(m.group(2))
        if not nums:
            continue
        # Prefer 4th numeric (Total) when Internal/Switching/Leakage/Total present
        val = nums[3] if len(nums) >= 4 else nums[-1]
        out[group] = val
    return out


def parse_total_watts(rpt: Path) -> float | None:
    groups = parse_group_watts(rpt)
    if "Total" in groups:
        return groups["Total"]
    text = rpt.read_text(errors="replace")
    m = re.search(r"Total\s+Power\s*[:=]?\s*([0-9.eE+-]+)", text, re.I)
    if m:
        return float(m.group(1))
    return None


def parse_instance_report_total(rpt: Path | None) -> float | None:
    """Best-effort total from a report_power -instances file."""
    if rpt is None or not rpt.is_file():
        return None
    groups = parse_group_watts(rpt)
    if "Total" in groups:
        return groups["Total"]
    text = rpt.read_text(errors="replace")
    for line in reversed(text.splitlines()):
        if re.search(r"\bTotal\b", line, re.I):
            nums = _nums(line)
            if nums:
                return nums[3] if len(nums) >= 4 else nums[-1]
    return None


def _enable_duty(interesting: dict) -> float | None:
    for key in ("sram_clk_en", "core_clk_en"):
        v = interesting.get(key)
        if isinstance(v, dict) and "duty" in v:
            return float(v["duty"])
    return None


def _blend_groups(awake: dict[str, float], sleep: dict[str, float], duty: float) -> dict[str, float]:
    keys = set(awake) | set(sleep)
    out: dict[str, float] = {}
    for k in keys:
        a = awake.get(k, 0.0)
        s = sleep.get(k, 0.0)
        out[k] = duty * a + (1.0 - duty) * s
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--activity-json", type=Path, required=True)
    ap.add_argument("--power-rpt", type=Path, required=True)
    ap.add_argument("--awake-rpt", type=Path, default=None,
                    help="OpenSTA report with core ICG GATE=1 (default: sibling power_awake.rpt)")
    ap.add_argument("--sleep-rpt", type=Path, default=None,
                    help="OpenSTA report with core ICG GATE=0 (default: sibling power_sleep.rpt)")
    ap.add_argument("--clock-rpt", type=Path, default=None)
    ap.add_argument("--design-period-ns", type=float, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    act = json.loads(args.activity_json.read_text())
    cycles = int(act.get("cycles") or 0)
    sim_period_ns = float(act.get("sim_period_ns") or 10.0)
    median = float(act.get("global_activity_median") or 0.0)
    interesting = act.get("interesting") or {}

    awake_rpt = args.awake_rpt
    sleep_rpt = args.sleep_rpt
    if awake_rpt is None:
        cand = args.power_rpt.with_name("power_awake.rpt")
        if cand.is_file():
            awake_rpt = cand
    if sleep_rpt is None:
        cand = args.power_rpt.with_name("power_sleep.rpt")
        if cand.is_file():
            sleep_rpt = cand

    duty = _enable_duty(interesting)
    blended = False
    if (
        awake_rpt is not None
        and sleep_rpt is not None
        and awake_rpt.is_file()
        and sleep_rpt.is_file()
        and duty is not None
    ):
        groups = _blend_groups(parse_group_watts(awake_rpt), parse_group_watts(sleep_rpt), duty)
        blended = True
        p_awake = parse_group_watts(awake_rpt).get("Total")
        p_sleep = parse_group_watts(sleep_rpt).get("Total")
    else:
        groups = parse_group_watts(args.power_rpt)
        p_awake = p_sleep = None

    p_w = groups.get("Total", parse_total_watts(args.power_rpt))
    design_period_ns = float(args.design_period_ns)
    f_hz = 1e9 / design_period_ns if design_period_ns else 0.0

    lines: list[str] = []
    lines.append("Activity-based power / energy summary")
    lines.append(f"vcd                 : {act.get('vcd')}")
    lines.append(f"cycles              : {cycles}")
    lines.append(f"vcd_sim_clock       : {1e3 / sim_period_ns:.4g} MHz ({sim_period_ns:g} ns TB period)")
    lines.append(f"design_clock        : {f_hz / 1e6:.4g} MHz ({design_period_ns:g} ns)")
    lines.append(f"activity_median     : {median:.6f} / cycle  (data path; clock uses create_clock)")
    for k, v in interesting.items():
        if isinstance(v, dict) and "activity" in v:
            extra = ""
            if "duty" in v:
                extra = f"  duty={v['duty']:.6f}"
            lines.append(f"  {k:18s}: act={v['activity']:.6f}{extra}")
    lines.append("")

    if p_w is None:
        lines.append("power_total         : (could not parse OpenSTA report)")
        lines.append(f"see                  : {args.power_rpt}")
    else:
        if blended and duty is not None:
            lines.append(
                f"power_total         : {p_w * 1e3:.6f} mW  ({p_w:.6e} W)  "
                f"[blended: duty*P_awake+(1-duty)*P_sleep]"
            )
            lines.append(f"core_clk_en_duty    : {duty:.6f}")
            if p_awake is not None:
                lines.append(f"power_awake         : {p_awake * 1e3:.6f} mW  (core ICG GATE=1)")
            if p_sleep is not None:
                lines.append(f"power_sleep         : {p_sleep * 1e3:.6f} mW  (core ICG GATE=0)")
        else:
            lines.append(f"power_total         : {p_w * 1e3:.6f} mW  ({p_w:.6e} W)")
        for g in ("Sequential", "Combinational", "Clock", "Macro", "Pad"):
            if g in groups:
                gw = groups[g]
                pct = 100.0 * gw / p_w if p_w else 0.0
                lines.append(f"  {g.lower():18s}: {gw * 1e3:.6f} mW  ({pct:.1f}%)")

        clk_named = parse_instance_report_total(args.clock_rpt)
        if clk_named is not None:
            lines.append(
                f"  clock_tree_named  : {clk_named * 1e3:.6f} mW  "
                f"(sum of *clkbuf*/clkinv/clkdly* cells; awake; see power_clock_tree.rpt)"
            )

        if cycles > 0 and design_period_ns > 0:
            t_s = cycles * design_period_ns * 1e-9
            e_j = p_w * t_s
            lines.append(f"runtime_one_infer   : {t_s * 1e3:.6f} ms")
            lines.append(f"energy_one_infer    : {e_j * 1e6:.6f} µJ  ({e_j:.6e} J)")
            lines.append("")
            lines.append("Note: energy ≈ P_avg × (cycles × design_period).")
            lines.append(
                "Clock tree: OpenSTA Clock group from create_clock + "
                "set_propagated_clock + SPEF (not VCD median)."
            )
            if blended:
                lines.append(
                    "Sleep: core ICG GATE case-analyzed; average is duty-weighted "
                    "blend of awake/sleep reports (set_power_activity on GATE is ignored)."
                )
            lines.append("Liberty / period should match the hardened run (TT 1.8 V).")

    args.output.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
