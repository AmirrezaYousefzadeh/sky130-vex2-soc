#!/usr/bin/env python3
"""Energy and latency of the event-driven N-MNIST workload from (a) the OpenSTA awake/sleep power of a gate-level
VCD window (power/run_avg_power.sh -> power_energy.txt) and (b) the testbench report of the full event stream
(simulation/run_sim.sh nmnist or run_gls.sh nmnist: "awake cycles per event", "DECISION at event", "PASS: ...").

The core sleeps (clock gated) between events, so
    E_event      = P_awake x awake_cycles_per_event x T_clk
    E_decision   = n_events_to_decision x E_event + P_sleep x (t_decision - awake time before the decision)
    E_sample     = n_events x E_event + P_sleep x (t_stream - total awake time)
    P_avg        = E_sample / t_stream   (real-time replay of the sample's event times)

  python3 power/nmnist_energy.py --power power/out_waveform_gls/power_energy.txt --sim simulation/nmnist_sim.log \
      --out docs/results/nmnist_energy.txt
"""
from __future__ import annotations
import argparse, re
from pathlib import Path


def grab(text, pat, cast=float, default=None):
    m = re.search(pat, text)
    return cast(m.group(1)) if m else default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--power", type=Path, required=True, help="power_energy.txt of run_avg_power.sh on the N-MNIST GLS VCD")
    ap.add_argument("--sim", type=Path, required=True, help="log of the full-stream firmware simulation (RTL or GLS)")
    ap.add_argument("--clk_ns", type=float, default=None, help="clock period (default: design_clock from the power file)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    pw = a.power.read_text(); sim = a.sim.read_text()
    p_awake = grab(pw, r"power_awake\s*:\s*([0-9.eE+-]+)\s*mW") * 1e-3
    p_sleep = grab(pw, r"power_sleep\s*:\s*([0-9.eE+-]+)\s*mW") * 1e-3
    clk_ns = a.clk_ns or grab(pw, r"design_clock\s*:.*?\(([0-9.]+)\s*ns\)", default=20.0)
    T = clk_ns * 1e-9
    n_ev = grab(sim, r"TB: (\d+) events delivered", int)
    awake_mean = grab(sim, r"awake cycles per event mean (\d+)", int)
    awake_max = grab(sim, r"awake cycles per event mean \d+ max (\d+)", int)
    late_n = grab(sim, r"late deliveries (\d+)", int, 0)
    late_max = grab(sim, r"late deliveries \d+ \(max (\d+) cycles\)", int, 0)
    dec_ev = grab(sim, r"DECISION at event (\d+)", int, -1)
    dec_ns = grab(sim, r"DECISION at event \d+, t=(\d+) ns", float)
    ev_ns = grab(sim, r"event time (\d+) ns", float)
    stream_cycles = grab(sim, r"stream_cycles=(\d+)", int)
    awake_total = grab(sim, r"awake_cycles=(\d+)", int)
    e_event = p_awake * awake_mean * T
    t_stream = stream_cycles * T
    e_sample = awake_total * T * p_awake + (stream_cycles - awake_total) * T * p_sleep
    lines = ["Event-driven N-MNIST on sky130_vex2_soc: energy / latency",
             f"power file      : {a.power}", f"sim log         : {a.sim}",
             f"clock           : {clk_ns:g} ns ({1e3/clk_ns:.1f} MHz)",
             f"P_awake / P_sleep : {p_awake*1e3:.3f} mW / {p_sleep*1e3:.3f} mW  (OpenSTA, core ICG case analysis)",
             f"events in stream: {n_ev}", f"awake cycles / event : mean {awake_mean}, max {awake_max}  ({awake_mean*clk_ns/1e3:.1f} us mean)",
             f"late deliveries : {late_n} (max backlog {late_max} cycles = {late_max*clk_ns/1e3:.1f} us)",
             f"energy / event  : {e_event*1e9:.1f} nJ",
             f"stream length   : {t_stream*1e3:.2f} ms, awake {awake_total*T*1e3:.2f} ms ({100*awake_total/stream_cycles:.1f} % duty)",
             f"energy / sample : {e_sample*1e6:.2f} uJ   (awake {awake_total*T*p_awake*1e6:.2f} uJ + sleep {(stream_cycles-awake_total)*T*p_sleep*1e6:.2f} uJ)",
             f"average power   : {e_sample/t_stream*1e3:.3f} mW at the sample's real-time event rate"]
    if dec_ev is not None and dec_ev >= 0 and dec_ns is not None:
        t_dec = dec_ns * 1e-9
        awake_to_dec = (dec_ev + 1) * awake_mean * T
        e_dec = (dec_ev + 1) * e_event + max(0.0, t_dec - awake_to_dec) * p_sleep
        lines += [f"decision        : event {dec_ev + 1} of {n_ev}, at {dec_ns/1e6:.2f} ms after stream start (event time {ev_ns/1e6:.2f} ms, "
                  f"processing backlog {(dec_ns-ev_ns)/1e3:.1f} us)",
                  f"energy to decision : {e_dec*1e6:.2f} uJ  ({(dec_ev+1)*e_event*1e6:.2f} uJ awake + {max(0.0, t_dec-awake_to_dec)*p_sleep*1e6:.2f} uJ sleep)"]
    else:
        lines.append("decision        : none within the stream")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_text(text); print("wrote", a.out)


if __name__ == "__main__":
    main()
