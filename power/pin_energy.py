#!/usr/bin/env python3
"""Energy of a workload from the per-pin power flow (run_pin_power.sh) and the testbench reports.

Event-driven N-MNIST (`--kind nmnist`): the short gate-level run (first K events) gives the total energy of its window
(per-pin power over the whole waveform, gated clock trees counted from the waveform) and an idle window gives the sleep
power with the free-running clock. Awake energy = total - P_sleep x sleep time; energy per event = awake energy / K;
awake power = awake energy / awake time. The full-stream testbench report (RTL) then gives events, awake cycles and the
decision, as in nmnist_energy.py:
    E_event, E_decision = n_dec x E_event + P_sleep x sleep time before the decision, E_sample, P_avg.
MNIST MLP (`--kind mnist`): the decode window (last wake before gpio_done .. gpio_done) gives the energy of one inference
directly; the idle window gives the sleep power.

  python3 power/pin_energy.py --kind nmnist --full power/out_pin_nmnist_full --idle power/out_pin_nmnist_idle \
      --windows power/out_pin_nmnist_windows.json --short_sim docs/results/nmnist_gls_short.txt \
      --sim docs/results/nmnist_sim.txt --out docs/results/nmnist_pin_energy.txt
  python3 power/pin_energy.py --kind mnist --decode power/out_pin_mnist_decode --idle power/out_pin_mnist_idle \
      --full power/out_pin_mnist_full --windows power/out_pin_mnist_windows.json --out docs/results/mnist_pin_energy.txt
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path


def grab(text, pat, cast=float, default=None):
    m = re.search(pat, text)
    return cast(m.group(1)) if m else default


def groups_line(s):
    g = s["groups"]
    return ", ".join(f"{k} {1e3*v['total_W']:.3f} mW" for k, v in g.items() if k != "total") + f"; leakage {1e3*g['total']['leakage_W']:.3f} mW"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["nmnist", "mnist"], required=True)
    ap.add_argument("--full", type=Path, help="run_pin_power output over the whole waveform")
    ap.add_argument("--idle", type=Path, required=True, help="run_pin_power output over the idle window")
    ap.add_argument("--decode", type=Path, help="mnist: run_pin_power output over the decode window")
    ap.add_argument("--windows", type=Path, required=True, help="vcd_windows.py output")
    ap.add_argument("--short_sim", type=Path, help="nmnist: testbench log of the short gate-level run")
    ap.add_argument("--sim", type=Path, help="nmnist: testbench log of the full-stream run")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    w = json.load(open(a.windows)); ts = w["timescale_s"]
    idle = json.load(open(a.idle / "summary.json")); p_sleep = idle["total_W"]
    clk_ns = idle["period_ns"]; T = clk_ns * 1e-9
    L = []
    if a.kind == "mnist":
        dec = json.load(open(a.decode / "summary.json")); full = json.load(open(a.full / "summary.json")) if a.full else None
        L += ["MNIST MLP on sky130_vex2_soc: per-pin OpenSTA energy",
              f"clock           : {clk_ns:g} ns ({1e3/clk_ns:.1f} MHz)",
              f"P_sleep (idle window, clock running, core gated) : {p_sleep*1e3:.3f} mW   [{groups_line(idle)}]",
              f"decode window   : {dec['duration_s']*1e3:.3f} ms ({dec['cycles']:.0f} cycles), power {dec['total_W']*1e3:.3f} mW   [{groups_line(dec)}]",
              f"energy / inference (decode window) : {dec['energy_J']*1e6:.3f} uJ"]
        if full:
            L += [f"whole waveform  : {full['duration_s']*1e3:.3f} ms, average power {full['total_W']*1e3:.3f} mW, energy {full['energy_J']*1e6:.3f} uJ, awake duty {100*w['awake_duty']:.1f} %"]
    else:
        full = json.load(open(a.full / "summary.json")); short = a.short_sim.read_text(); sim = a.sim.read_text()
        k = grab(short, r"TB: (\d+) events delivered", int); awake_short = grab(short, r"awake_cycles=(\d+)", int)
        t_total = full["duration_s"]; t_awake = w["awake_cycles"] * T
        e_awake = full["energy_J"] - p_sleep * (t_total - t_awake)
        p_awake = e_awake / t_awake; e_event = e_awake / k
        n_ev = grab(sim, r"TB: (\d+) events delivered", int); awake_mean = grab(sim, r"awake cycles per event mean (\d+)", int)
        awake_max = grab(sim, r"awake cycles per event mean \d+ max (\d+)", int); late_n = grab(sim, r"late deliveries (\d+)", int, 0)
        late_max = grab(sim, r"late deliveries \d+ \(max (\d+) cycles\)", int, 0); dec_ev = grab(sim, r"DECISION at event (\d+)", int, -1)
        dec_ns = grab(sim, r"DECISION at event \d+, t=(\d+) ns", float); ev_ns = grab(sim, r"event time (\d+) ns", float)
        stream_cycles = grab(sim, r"stream_cycles=(\d+)", int); awake_total = grab(sim, r"awake_cycles=(\d+)", int)
        e_event_cyc = p_awake * T   # energy per awake cycle
        e_sample = awake_total * e_event_cyc + (stream_cycles - awake_total) * T * p_sleep; t_stream = stream_cycles * T
        n_ev = n_ev or k; awake_mean = awake_mean or int(round(awake_short / k))
        L += ["Event-driven N-MNIST on sky130_vex2_soc: per-pin OpenSTA energy / latency",
              f"clock           : {clk_ns:g} ns ({1e3/clk_ns:.1f} MHz)",
              f"gate-level window : first {k} events, {t_total*1e3:.3f} ms, awake {t_awake*1e3:.3f} ms ({100*w['awake_duty']:.1f} %), "
              f"average power {full['total_W']*1e3:.3f} mW   [{groups_line(full)}]",
              f"P_sleep (idle window, clock running, core gated) : {p_sleep*1e3:.3f} mW   [{groups_line(idle)}]",
              f"P_awake (derived) : {p_awake*1e3:.3f} mW   ({p_awake*T*1e12:.1f} pJ per awake cycle)",
              f"energy / event  : {p_awake*T*awake_mean*1e9:.1f} nJ at the full-stream mean of {awake_mean} awake cycles per event "
              f"({e_event*1e9:.1f} nJ at the {awake_short/k:.0f} cycles per event of the gate-level window)",
              f"full stream (RTL testbench): {n_ev} events, awake cycles / event mean {awake_mean}, max {awake_max} ({awake_mean*clk_ns/1e3:.1f} us); "
              f"late deliveries {late_n} (max backlog {late_max*clk_ns/1e3:.1f} us); awake {awake_total*T*1e3:.2f} of {t_stream*1e3:.2f} ms ({100*awake_total/stream_cycles:.1f} % duty)",
              f"energy / sample : {e_sample*1e6:.2f} uJ   (awake {awake_total*e_event_cyc*1e6:.2f} uJ + sleep {(stream_cycles-awake_total)*T*p_sleep*1e6:.2f} uJ)",
              f"average power   : {e_sample/t_stream*1e3:.3f} mW at the sample's real-time event rate"]
        if dec_ev is not None and dec_ev >= 0 and dec_ns is not None:
            t_dec = dec_ns * 1e-9; awake_to_dec = (dec_ev + 1) * awake_mean * T
            e_dec = (dec_ev + 1) * awake_mean * e_event_cyc + max(0.0, t_dec - awake_to_dec) * p_sleep
            L += [f"decision        : event {dec_ev+1} of {n_ev}, at {dec_ns/1e6:.2f} ms after stream start (event time {ev_ns/1e6:.2f} ms, backlog {(dec_ns-ev_ns)/1e3:.1f} us)",
                  f"energy to decision : {e_dec*1e6:.2f} uJ  ({(dec_ev+1)*awake_mean*e_event_cyc*1e6:.2f} uJ awake + {max(0.0, t_dec-awake_to_dec)*p_sleep*1e6:.2f} uJ sleep)"]
    text = "\n".join(L) + "\n"; print(text)
    if a.out: a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_text(text); print("wrote", a.out)


if __name__ == "__main__":
    main()
