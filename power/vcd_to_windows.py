#!/usr/bin/env python3
"""Slice a VCD into N equal time windows and extract per-window activity.

Writes:
  - windows.json   metadata + per-window activity summaries
  - activity_windows.tcl   OpenSTA arrays (::tp_*)
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


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def parse_timescale_and_end(path: Path) -> tuple[str, int]:
    """Return (timescale_body, end_time). End time from tail scan when possible."""
    timescale = "1ns"
    with path.open("r", errors="replace") as f:
        for _ in range(50):
            line = f.readline()
            if not line:
                break
            if line.startswith("$timescale"):
                body = line[len("$timescale") :].strip()
                if not body or body == "$end":
                    body = f.readline().strip()
                timescale = body.replace("$end", "").strip() or timescale
                break

    size = path.stat().st_size
    tmax = 0
    with path.open("r", errors="replace") as f:
        if size > 2_000_000:
            f.seek(size - 2_000_000)
            f.readline()
        for line in f:
            if line.startswith("#"):
                s = line[1:].strip()
                if s.isdigit():
                    tmax = int(s)
    if tmax <= 0:
        _progress("  tail scan missed end time; full timestamp scan...")
        with path.open("r", errors="replace") as f:
            for line in f:
                if line.startswith("#"):
                    s = line[1:].strip()
                    if s.isdigit():
                        tmax = int(s)
    return timescale, tmax


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.1
    s = sorted(vals)
    return s[len(s) // 2]


def _finalize_window(
    *,
    index: int,
    t0: int,
    t1: int,
    id_meta: dict[str, tuple[int, str]],
    rises: dict[str, int],
    high_time: dict[str, int],
    clk_rises: int,
    scope_prefix: str,
    clk_name: str,
    window_dt: int,
) -> dict:
    cycles = max(clk_rises, 1)
    duration = max(window_dt, 1)
    interesting: dict[str, dict] = {}
    scalar_acts: list[float] = []

    for vid, (w, h) in id_meta.items():
        r = rises.get(vid, 0)
        act = (r / cycles) if w == 1 else (r / (cycles * w))
        act_c = min(max(act, 0.0), 2.0)
        duty = (high_time.get(vid, 0) / duration) if w == 1 else 0.5
        short = h[len(scope_prefix) + 1 :] if h.startswith(scope_prefix + ".") else h
        if w == 1 and short != clk_name and not short.endswith(".clk") and short != "sram_clk":
            scalar_acts.append(act_c)
        for key, names in ALIASES.items():
            if short in names and key not in interesting:
                interesting[key] = {
                    "activity": act_c,
                    "duty": min(max(duty, 0.0), 1.0),
                    "rises": r,
                }

    median = _median(scalar_acts) if scalar_acts else 0.0
    # Empty / no-clock windows still need a floor so OpenSTA does not go weird.
    # Do NOT floor real quiet windows (e.g. busy-wait sleep): that hid power dips.
    if clk_rises == 0 and not scalar_acts:
        median = 0.01
    median = min(max(median, 0.0), 0.5)

    return {
        "index": index,
        "t0": t0,
        "t1": t1,
        "cycles": clk_rises,
        "global_activity_median": median,
        "interesting": interesting,
    }


def parse_vcd_windows(
    path: Path,
    scope_prefix: str,
    clk_name: str,
    n_windows: int,
) -> dict:
    timescale, end_time = parse_timescale_and_end(path)
    if end_time <= 0:
        raise SystemExit(f"VCD has no timestamps: {path}")
    if n_windows < 1:
        raise SystemExit("--windows must be >= 1")

    t_start = 0
    span = end_time - t_start
    # Equal slots; last window includes end_time.
    edges = [t_start + (span * i) // n_windows for i in range(n_windows + 1)]
    edges[-1] = end_time

    id_meta: dict[str, tuple[int, str]] = {}
    values: dict[str, int] = {}
    rises: dict[str, int] = defaultdict(int)
    high_time: dict[str, int] = defaultdict(int)
    last_t = 0
    t = 0
    in_defs = True
    scopes: list[str] = []
    clk_id = None
    clk_rises = 0
    win_i = 0
    windows: list[dict] = []

    var_re = re.compile(
        r"^\$var\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[0-9]+:[0-9]+\])?\s+\$end"
    )

    def hier(name: str) -> str:
        return ".".join(scopes + [name]) if scopes else name

    def in_scope(h: str) -> bool:
        return h == scope_prefix or h.startswith(scope_prefix + ".")

    def flush_to(target_win: int) -> None:
        nonlocal win_i, rises, high_time, clk_rises
        while win_i < target_win and win_i < n_windows:
            t0, t1 = edges[win_i], edges[win_i + 1]
            windows.append(
                _finalize_window(
                    index=win_i,
                    t0=t0,
                    t1=t1,
                    id_meta=id_meta,
                    rises=rises,
                    high_time=high_time,
                    clk_rises=clk_rises,
                    scope_prefix=scope_prefix,
                    clk_name=clk_name,
                    window_dt=max(t1 - t0, 1),
                )
            )
            rises = defaultdict(int)
            high_time = defaultdict(int)
            clk_rises = 0
            win_i += 1

    def accumulate_duty(dt: int) -> None:
        if dt <= 0:
            return
        for vid, val in values.items():
            w, _ = id_meta[vid]
            if w == 1 and val == 1:
                high_time[vid] += dt

    def advance_time(newt: int) -> None:
        nonlocal last_t, t
        if newt < last_t:
            raise SystemExit(f"time went backwards at {newt}")
        # Split [last_t, newt) across window boundaries.
        cur = last_t
        while cur < newt and win_i < n_windows:
            boundary = edges[win_i + 1]
            chunk_end = min(newt, boundary)
            accumulate_duty(chunk_end - cur)
            cur = chunk_end
            if cur >= boundary and newt >= boundary:
                # Close window at boundary before continuing.
                flush_to(win_i + 1)
        last_t = newt
        t = newt

    size = path.stat().st_size
    _progress(
        f"==> Windowing VCD into {n_windows} equal slots "
        f"[0, {end_time}] timescale={timescale}"
    )
    t_wall0 = time.time()
    next_pct = 5

    with path.open("r", errors="replace") as f:
        while True:
            line = f.readline()
            if not line:
                break
            # Progress by file position
            if size > 0:
                pct = int(100 * f.tell() / size)
                if pct >= next_pct:
                    elapsed = max(time.time() - t_wall0, 1e-6)
                    mb_s = (f.tell() / 1e6) / elapsed
                    _progress(
                        f"  VCD parse {pct:3d}%  "
                        f"{f.tell()/1e6:.0f}/{size/1e6:.0f} MB  "
                        f"{mb_s:.1f} MB/s  window={win_i}/{n_windows}"
                    )
                    next_pct = pct + 5

            line = line.strip()
            if not line:
                continue

            if in_defs:
                if line.startswith("$scope"):
                    parts = line.split()
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
                    _progress(f"  signals in scope: {len(id_meta)}")
                continue

            if line.startswith("#"):
                advance_time(int(line[1:]))
                continue

            if line[0] in "01xXzZ" and len(line) >= 2 and not line.startswith(("b", "r")):
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
                values[vid] = newv
                continue

            if line.startswith(("b", "B")):
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
                w, _ = id_meta[vid]
                if old is not None and newv != old:
                    xor = old ^ newv
                    risen = xor & newv
                    rises[vid] += risen.bit_count()
                values[vid] = newv
                continue

    # Flush remaining time to end and remaining windows.
    if t < end_time:
        advance_time(end_time)
    flush_to(n_windows)
    while len(windows) < n_windows:
        i = len(windows)
        windows.append(
            _finalize_window(
                index=i,
                t0=edges[i],
                t1=edges[i + 1],
                id_meta=id_meta,
                rises={},
                high_time={},
                clk_rises=0,
                scope_prefix=scope_prefix,
                clk_name=clk_name,
                window_dt=max(edges[i + 1] - edges[i], 1),
            )
        )

    elapsed = time.time() - t_wall0
    _progress(f"  VCD parse done in {elapsed:.1f}s  windows={len(windows)}")

    return {
        "vcd": str(path.resolve()),
        "scope": scope_prefix,
        "timescale": timescale,
        "t_start": t_start,
        "t_end": end_time,
        "n_windows": n_windows,
        "n_signals": len(id_meta),
        "sim_period_ns": 10.0,
        "windows": windows,
    }


def write_activity_tcl(stats: dict, out: Path, design_period_ns: float) -> None:
    lines = [
        f"# Auto-generated window activity from {stats['vcd']}",
        f"set ::tp_n {stats['n_windows']}",
        f"set ::mnist_design_period_ns {design_period_ns}",
        f"set ::tp_design_period_ns {design_period_ns}",
    ]
    for w in stats["windows"]:
        i = w["index"]
        g = w["global_activity_median"]
        lines.append(f"set ::tp_global({i}) {g:.6f}")
        for k, v in w.get("interesting", {}).items():
            lines.append(f"set ::tp_act({i},{k}) {v['activity']:.6f}")
            lines.append(f"set ::tp_duty({i},{k}) {v['duty']:.6f}")
    out.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("vcd", type=Path)
    ap.add_argument("--scope", default="tb_fw_mnist.u_soc")
    ap.add_argument("--clk", default="clk")
    ap.add_argument("--windows", type=int, default=1000)
    ap.add_argument("--design-period-ns", type=float, default=20.0)
    ap.add_argument("-o", "--out-json", type=Path, required=True)
    ap.add_argument("--sta-tcl", type=Path, required=True)
    args = ap.parse_args()

    stats = parse_vcd_windows(args.vcd, args.scope, args.clk, args.windows)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(stats, indent=2) + "\n")
    write_activity_tcl(stats, args.sta_tcl, args.design_period_ns)
    _progress(f"wrote {args.out_json}")
    _progress(f"wrote {args.sta_tcl}")


if __name__ == "__main__":
    main()
