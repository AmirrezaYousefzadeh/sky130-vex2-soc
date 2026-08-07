#!/usr/bin/env python3
"""Extract switching activity from an RTL VCD for OpenSTA power analysis.

OpenSTA activity = probability of a 0→1 transition per clock cycle.
Duty = fraction of time the signal is high.

The MNIST VCD is RTL (tb_fw_mnist.u_soc.*). Gate-level names will not match,
so we export a global activity (and key SoC/SRAM pin rates) for set_power_activity.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def parse_vcd_activity(path: Path, scope_prefix: str, clk_name: str) -> dict:
    # id -> (width, hier_name)
    id_meta: dict[str, tuple[int, str]] = {}
    # id -> current int value (bitwise for vectors tracked as whole; we expand bits)
    values: dict[str, int] = {}
    rises: dict[str, int] = defaultdict(int)
    falls: dict[str, int] = defaultdict(int)
    high_time: dict[str, int] = defaultdict(int)
    last_t = 0
    t = 0
    in_defs = True
    scopes: list[str] = []
    clk_id = None
    clk_rises = 0
    clk_prev = None

    var_re = re.compile(
        r"^\$var\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[0-9]+:[0-9]+\])?\s+\$end"
    )

    def hier(name: str) -> str:
        return ".".join(scopes + [name]) if scopes else name

    def in_scope(h: str) -> bool:
        return h == scope_prefix or h.startswith(scope_prefix + ".")

    with path.open("r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if in_defs:
                if line.startswith("$scope"):
                    parts = line.split()
                    # $scope module name $end
                    if len(parts) >= 3:
                        scopes.append(parts[2])
                elif line.startswith("$upscope"):
                    if scopes:
                        scopes.pop()
                elif line.startswith("$var"):
                    m = var_re.match(line)
                    if not m:
                        continue
                    width, vid, name = int(m.group(1)), m.group(2), m.group(3)
                    h = hier(name)
                    if in_scope(h):
                        # First alias wins (VCD reuses ids for aliases).
                        if vid not in id_meta:
                            id_meta[vid] = (width, h)
                        if h == f"{scope_prefix}.{clk_name}":
                            clk_id = vid
                elif line.startswith("$enddefinitions"):
                    in_defs = False
                    if clk_id is None:
                        for vid, (w, h) in id_meta.items():
                            if h == f"{scope_prefix}.{clk_name}" and w == 1:
                                clk_id = vid
                                break
                    if clk_id is None:
                        raise SystemExit("Could not find clk in VCD scope")
                continue

            if line.startswith("#"):
                newt = int(line[1:])
                dt = newt - last_t
                if dt < 0:
                    raise SystemExit(f"time went backwards at {newt}")
                # accumulate duty for known scalar bits
                for vid, val in values.items():
                    w, _ = id_meta[vid]
                    if w == 1 and val == 1:
                        high_time[vid] += dt
                last_t = newt
                t = newt
                continue

            # value change: 0!, 1$, bxxxx id, rX.X id
            if line[0] in "01xXzZ" and len(line) >= 2 and not line.startswith("b") and not line.startswith("r"):
                val_c, vid = line[0], line[1:]
                if vid not in id_meta:
                    continue
                w, _ = id_meta[vid]
                if w != 1:
                    continue
                newv = 0 if val_c in "0" else (1 if val_c in "1" else values.get(vid, 0))
                old = values.get(vid)
                if old is not None and newv != old:
                    if old == 0 and newv == 1:
                        rises[vid] += 1
                        if vid == clk_id:
                            clk_rises += 1
                    elif old == 1 and newv == 0:
                        falls[vid] += 1
                values[vid] = newv
                continue

            if line.startswith("b") or line.startswith("B"):
                # b<bits> <id>
                parts = line.split()
                if len(parts) != 2:
                    continue
                bits, vid = parts[0][1:], parts[1]
                if vid not in id_meta:
                    continue
                try:
                    newv = int(bits.replace("x", "0").replace("z", "0").replace("X", "0").replace("Z", "0"), 2)
                except ValueError:
                    continue
                old = values.get(vid)
                w, h = id_meta[vid]
                if old is not None and newv != old:
                    # count bit-level 0→1 for activity average
                    xor = old ^ newv
                    # rises where new bit is 1
                    risen = xor & newv
                    rises[vid] += risen.bit_count() if hasattr(int, "bit_count") else bin(risen).count("1")
                    fallen = xor & old
                    falls[vid] += fallen.bit_count() if hasattr(int, "bit_count") else bin(fallen).count("1")
                values[vid] = newv
                continue

    cycles = max(clk_rises, 1)
    duration = max(t, 1)

    records = []
    total_act = 0.0
    total_bits = 0
    interesting = {}
    for vid, (w, h) in id_meta.items():
        r = rises.get(vid, 0)
        # For vectors, r already counts bit-rises; activity per bit ≈ r/(w*cycles)
        act = (r / cycles) if w == 1 else (r / (cycles * w))
        duty = (high_time.get(vid, 0) / duration) if w == 1 else 0.5
        # clamp to OpenSTA-reasonable range
        act_c = min(max(act, 0.0), 2.0)
        short = h[len(scope_prefix) + 1 :] if h.startswith(scope_prefix + ".") else h
        rec = {
            "name": h,
            "short": short,
            "width": w,
            "rises": r,
            "activity": act_c,
            "duty": duty,
        }
        records.append(rec)
        if w == 1 and short != clk_name and "clk" not in short.split(".")[-1]:
            total_act += act_c
            total_bits += 1
        aliases = {
            "imem_ce": ("imem_ce", "u_imem.ce"),
            "dmem_ce": ("dmem_ce", "u_dmem.ce"),
            "dmem_we": ("dmem_we", "u_dmem.we"),
            "imem_we": ("imem_we", "u_imem.we"),
            "sram_clk_en": ("sram_clk_en",),
            "halted": ("halted",),
            "reset": ("reset",),
        }
        for key, names in aliases.items():
            if short in names and key not in interesting:
                interesting[key] = rec

    global_activity = (total_act / total_bits) if total_bits else 0.1
    # Exclude near-static signals from skewing global? use median of scalar activities
    scalar_acts = sorted(
        r["activity"]
        for r in records
        if r["width"] == 1
        and r["short"] != clk_name
        and not r["short"].endswith(".clk")
        and r["short"] != "sram_clk"
    )
    median_activity = scalar_acts[len(scalar_acts) // 2] if scalar_acts else global_activity
    total_act = sum(scalar_acts)
    total_bits = len(scalar_acts)
    global_activity = (total_act / total_bits) if total_bits else 0.1

    return {
        "vcd": str(path),
        "scope": scope_prefix,
        "timescale_note": "VCD timestamps; TB used 10 ns period (100 MHz)",
        "sim_period_ns": 10.0,
        "end_time": t,
        "clock_rises": clk_rises,
        "cycles": cycles,
        "n_signals": len(records),
        "global_activity_mean": global_activity,
        "global_activity_median": median_activity,
        "interesting": {k: {"activity": v["activity"], "duty": v["duty"], "rises": v["rises"]} for k, v in interesting.items()},
        # top toggles for debug
        "top_active": sorted(
            (
                {"short": r["short"], "activity": r["activity"], "width": r["width"]}
                for r in records
                if r["width"] == 1
            ),
            key=lambda x: -x["activity"],
        )[:30],
    }


def write_sta_tcl(stats: dict, out: Path, design_period_ns: float) -> None:
    # Prefer median — mean is inflated by a few always-toggling nets.
    g = stats["global_activity_median"]
    g = min(max(g, 0.01), 0.5)
    lines = [
        f"# Auto-generated from {stats['vcd']}",
        f"# RTL sim cycles={stats['cycles']} @ {stats['sim_period_ns']} ns; "
        f"power annotated at design period {design_period_ns} ns",
        f"set ::mnist_global_activity {g:.6f}",
        f"set ::mnist_design_period_ns {design_period_ns}",
    ]
    for k, v in stats.get("interesting", {}).items():
        lines.append(f"set ::mnist_act({k}) {v['activity']:.6f}")
        lines.append(f"set ::mnist_duty({k}) {v['duty']:.6f}")
    out.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("vcd", type=Path)
    ap.add_argument("--scope", default="tb_fw_mnist.u_soc")
    ap.add_argument("--clk", default="clk")
    ap.add_argument("--design-period-ns", type=float, default=40.0)
    ap.add_argument("-o", "--out-json", type=Path, required=True)
    ap.add_argument("--sta-tcl", type=Path, help="Write OpenSTA activity variables")
    args = ap.parse_args()

    stats = parse_vcd_activity(args.vcd, args.scope, args.clk)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(stats, indent=2) + "\n")
    print(
        f"cycles={stats['cycles']}  mean_act={stats['global_activity_mean']:.4f}  "
        f"median_act={stats['global_activity_median']:.4f}"
    )
    print("interesting:", json.dumps(stats["interesting"], indent=2))
    if args.sta_tcl:
        write_sta_tcl(stats, args.sta_tcl, args.design_period_ns)
        print(f"wrote {args.sta_tcl}")


if __name__ == "__main__":
    main()
