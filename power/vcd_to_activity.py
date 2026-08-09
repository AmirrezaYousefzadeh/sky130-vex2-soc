#!/usr/bin/env python3
"""Extract switching activity from a VCD for OpenSTA power analysis.

OpenSTA activity = probability of a 0→1 transition per clock cycle.
Duty = fraction of time the signal is high.

Prefer a gate-level VCD (simulation/run_gls.sh): net names match the post-PnR
netlist, so the median activity is representative. RTL VCDs still work, but
unmatched gate nets fall back to that median in OpenSTA.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path


ALIASES = {
    "imem_ce": ("imem_ce", "u_imem.ce"),
    "dmem_ce": ("dmem_ce", "u_dmem.ce"),
    "dmem_we": ("dmem_we", "u_dmem.we"),
    "imem_we": ("imem_we", "u_imem.we"),
    # sram_clk_en is the SoC port tied to core_clk_en (sleep ICG GATE).
    "sram_clk_en": ("sram_clk_en", "core_clk_en"),
    "halted": ("halted",),
    "reset": ("reset",),
}


def _progress(msg: str, *, nl: bool = True) -> None:
    end = "\n" if nl else ""
    print(msg, end=end, file=sys.stderr, flush=True)


def parse_vcd_activity(path: Path, scope_prefix: str, clk_name: str) -> dict:
    # id -> (width, hier_name)
    id_meta: dict[str, tuple[int, str]] = {}
    # id -> current int value
    values: dict[str, int] = {}
    rises: dict[str, int] = defaultdict(int)
    falls: dict[str, int] = defaultdict(int)
    # Duty only needed for a handful of ports we hand to OpenSTA — not all nets.
    high_time: dict[str, int] = defaultdict(int)
    duty_ids: set[str] = set()
    last_t = 0
    t = 0
    in_defs = True
    scopes: list[str] = []
    clk_id = None
    clk_rises = 0

    var_re = re.compile(
        r"^\$var\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[0-9]+:[0-9]+\])?\s+\$end"
    )
    alias_shorts = {n for names in ALIASES.values() for n in names}

    def hier(name: str) -> str:
        return ".".join(scopes + [name]) if scopes else name

    def in_scope(h: str) -> bool:
        return h == scope_prefix or h.startswith(scope_prefix + ".")

    size = path.stat().st_size
    size_mb = max(size / 1e6, 1e-6)
    t_wall0 = time.time()
    next_pct = 5
    last_prog_wall = t_wall0
    bar_w = 28

    def show_progress(*, force: bool = False) -> None:
        nonlocal next_pct, last_prog_wall
        now = time.time()
        pos = f.tell()
        pct = int(100 * pos / size) if size > 0 else 100
        # Update on 5% boundaries or every ~2s so the bar is visible in terminals
        # that do not render carriage-return well.
        if not force and pct < next_pct and (now - last_prog_wall) < 2.0:
            return
        while next_pct <= pct:
            next_pct += 5
        elapsed = max(now - t_wall0, 1e-6)
        mb_s = (pos / 1e6) / elapsed
        remain = max(size - pos, 0)
        eta = remain / (pos / elapsed) if pos > 0 else 0.0
        eta_m, eta_s = divmod(int(eta), 60)
        fill = min(bar_w, int(bar_w * pct / 100))
        bar = "#" * fill + "-" * (bar_w - fill)
        _progress(
            f"  [{bar}] {pct:3d}%  "
            f"{pos/1e6:.0f}/{size_mb:.0f} MB  "
            f"{mb_s:.1f} MB/s  ETA {eta_m}m{eta_s:02d}s  "
            f"t={t}  cyc~{clk_rises}"
        )
        last_prog_wall = now

    _progress(f"==> Parsing VCD activity ({size_mb:.0f} MB): {path}")

    with path.open("r", errors="replace") as f:
        while True:
            line = f.readline()
            if not line:
                break

            show_progress()

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
                        short = (
                            h[len(scope_prefix) + 1 :]
                            if h.startswith(scope_prefix + ".")
                            else h
                        )
                        if width == 1 and short in alias_shorts:
                            duty_ids.add(vid)
                elif line.startswith("$enddefinitions"):
                    in_defs = False
                    if clk_id is None:
                        for vid, (w, h) in id_meta.items():
                            if h == f"{scope_prefix}.{clk_name}" and w == 1:
                                clk_id = vid
                                break
                    if clk_id is None:
                        raise SystemExit("Could not find clk in VCD scope")
                    _progress(
                        f"  signals in scope: {len(id_meta)}  "
                        f"(duty-tracked ports: {len(duty_ids)})"
                    )
                continue

            if line.startswith("#"):
                newt = int(line[1:])
                dt = newt - last_t
                if dt < 0:
                    raise SystemExit(f"time went backwards at {newt}")
                # Only accumulate duty for ports we pass to OpenSTA.
                if dt and duty_ids:
                    for vid in duty_ids:
                        if values.get(vid) == 1:
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
                    newv = int(
                        bits.replace("x", "0")
                        .replace("z", "0")
                        .replace("X", "0")
                        .replace("Z", "0"),
                        2,
                    )
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

        show_progress(force=True)

    elapsed = time.time() - t_wall0
    _progress(f"  VCD parse done in {elapsed:.1f}s  t={t}  cycles={clk_rises}")

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
        duty = (high_time.get(vid, 0) / duration) if vid in duty_ids else 0.5
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
        for key, names in ALIASES.items():
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
        "interesting": {
            k: {"activity": v["activity"], "duty": v["duty"], "rises": v["rises"]}
            for k, v in interesting.items()
        },
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
    src = stats["vcd"]
    gls = "gls" in Path(src).name.lower() or "gate" in Path(src).name.lower()
    lines = [
        f"# Auto-generated from {src}",
        f"# {'Gate-level' if gls else 'RTL'} sim cycles={stats['cycles']} @ "
        f"{stats['sim_period_ns']} ns; power annotated at design period "
        f"{design_period_ns} ns",
        f"set ::mnist_global_activity {g:.6f}",
        f"set ::mnist_design_period_ns {design_period_ns}",
        f"set ::mnist_vcd_is_gls {'1' if gls else '0'}",
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
