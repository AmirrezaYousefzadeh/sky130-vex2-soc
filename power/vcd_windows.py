#!/usr/bin/env python3
"""Windows of a gate-level SoC waveform for the per-pin power flow (streamed, the VCD is never held in memory).

Reads clk, sram_clk_en (core clock enable), wake and gpio_done of the u_soc scope and reports, in VCD time units:
  full          : first .. last timestamp
  awake         : list of [begin, end] intervals in which the core clock was enabled, with their cycle counts
  idle          : the longest interval with the core clock gated (sleep power with the free-running clock)
  decode        : last `wake` before the first `gpio_done` rise .. that rise (the MNIST inference window; absent otherwise)
Usage: vcd_windows.py <vcd> -o windows.json
"""
from __future__ import annotations
import argparse, json, re, subprocess
from pathlib import Path

TS = {"1s": 1.0, "1ms": 1e-3, "1us": 1e-6, "1ns": 1e-9, "100ps": 1e-10, "10ps": 1e-11, "1ps": 1e-12, "1fs": 1e-15}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vcd", type=Path); ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--scope-suffix", default="u_soc")
    a = ap.parse_args()
    want = {"clk", "sram_clk_en", "gpio_done", "wake"}; ids = {}; scopes = []; tscale = "1ns"
    with a.vcd.open(errors="replace") as f:
        for line in f:
            if line.startswith("$timescale"):
                body = line.replace("$timescale", "").replace("$end", "").strip()
                if not body: body = next(f).replace("$end", "").strip()
                tscale = body.replace(" ", "")
            elif line.startswith("$scope"): scopes.append(line.split()[2])
            elif line.startswith("$upscope"): scopes.pop()
            elif line.startswith("$var"):
                m = re.match(r"\$var\s+\S+\s+(\d+)\s+(\S+)\s+(\S+)", line)
                if m and int(m.group(1)) == 1 and m.group(3) in want and ".".join(scopes).endswith(a.scope_suffix): ids.setdefault(m.group(2), m.group(3))
            elif line.startswith("$enddefinitions"): break
    if "clk" not in ids.values(): raise SystemExit("clk not found in scope " + a.scope_suffix)
    pat = "^(#[0-9]+|(" + "|".join("[01]" + re.escape(v) for v in ids) + "))$"
    proc = subprocess.Popen(["grep", "-a", "-E", pat, str(a.vcd)], stdout=subprocess.PIPE, text=True, errors="replace")
    t = 0; vals = {}; wakes = []; done = None; t_min = None; t_max = 0
    rises = 0; awake_rises = 0; awake = []; cur_begin = None; cur_cycles = 0
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line: continue
        if line[0] == "#":
            t = int(line[1:]); t_max = t
            if t_min is None: t_min = t
            continue
        name = ids[line[1:]]; v = int(line[0]); old = vals.get(name); vals[name] = v
        if name == "clk" and old == 0 and v == 1:
            rises += 1
            if vals.get("sram_clk_en", 0) == 1: awake_rises += 1; cur_cycles += 1
        elif name == "sram_clk_en" and old != v:
            if v == 1: cur_begin = t; cur_cycles = 0
            elif cur_begin is not None: awake.append([cur_begin, t, cur_cycles]); cur_begin = None
        elif name == "wake" and old != v and v == 1: wakes.append(t)
        elif name == "gpio_done" and old != v and v == 1 and done is None: done = t
    if cur_begin is not None: awake.append([cur_begin, t_max, cur_cycles])
    # idle: the longest gap between awake intervals (or before the first / after the last)
    gaps = []
    prev = t_min
    for b, e, _ in awake:
        if b - prev > 0: gaps.append([prev, b])
        prev = e
    if t_max - prev > 0: gaps.append([prev, t_max])
    idle = max(gaps, key=lambda g: g[1] - g[0]) if gaps else None
    res = {"vcd": str(a.vcd), "timescale": tscale, "timescale_s": TS.get(tscale, 1e-9), "t_min": t_min, "t_max": t_max,
           "clock_rises": rises, "awake_cycles": awake_rises, "awake_duty": awake_rises / max(1, rises),
           "n_awake_intervals": len(awake), "awake_intervals": awake if len(awake) <= 4000 else awake[:4000],
           "idle": idle, "wakes": wakes if len(wakes) <= 4000 else wakes[:4000], "gpio_done": done}
    if done is not None and any(w < done for w in wakes):
        res["decode"] = [max(w for w in wakes if w < done), done]
    a.out.write_text(json.dumps(res, indent=1))
    print(f"{a.vcd.name}: {tscale}, {rises} cycles, awake {awake_rises} ({100*res['awake_duty']:.1f} %), {len(awake)} awake intervals, "
          f"idle window {idle}, decode window {res.get('decode')}")


if __name__ == "__main__":
    main()
