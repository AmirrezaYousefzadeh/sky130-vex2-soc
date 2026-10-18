#!/usr/bin/env python3
"""Make a shortened copy of an exported N-MNIST sample (first K events) for short gate-level power runs.

Reads weights.h / events.hex / events.vh from --src, recomputes the reference output integrators and the decision
for the first K events with the same exact per-event arithmetic as the firmware, and writes the three files to --dst.

  python3 trim_sample.py --src firmware/nmnist --dst firmware/nmnist/short100 --events 100
"""
from __future__ import annotations
import argparse, re
from pathlib import Path
import numpy as np


def c_array(text, name):
    m = re.search(rf"\b{name}\[(\d+)\]\s*=\s*\{{([^}}]*)\}}", text)
    return np.array([int(v) for v in m.group(2).split(",")], np.int64)


def define(text, name, cast=int):
    return cast(re.search(rf"#define\s+{name}\s+(-?\d+)", text).group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--dst", type=Path, required=True)
    ap.add_argument("--events", type=int, required=True)
    a = ap.parse_args()
    h = (a.src / "weights.h").read_text()
    hid, out, theta, margin, refr = (define(h, n) for n in ("NMNIST_HID", "NMNIST_OUT", "NMNIST_THETA", "NMNIST_MARGIN", "NMNIST_REFRACTORY"))
    W1 = c_array(h, "W1").reshape(-1, hid); W2 = c_array(h, "W2").reshape(hid, out); ev = c_array(h, "EVENTS")[:a.events]
    v = np.zeros(hid, np.int64); o = np.zeros(out, np.int64); fired = np.zeros(hid, bool); nsp = 0; dec = -1
    for e, c in enumerate(ev):
        v = np.clip(v + W1[c], -32768, 32767); s = v >= theta
        if refr: s &= ~fired; fired |= s
        if s.any(): v[s] = 0; o = o + W2[s].sum(0); nsp += int(s.sum())
        srt = np.sort(o)
        if dec < 0 and srt[-1] - srt[-2] >= margin: dec = e
    h2 = re.sub(r"#define NMNIST_N_EV \d+", f"#define NMNIST_N_EV {len(ev)}", h)
    h2 = re.sub(r"#define NMNIST_REF_DECISION_EV -?\d+", f"#define NMNIST_REF_DECISION_EV {dec}", h2)
    h2 = re.sub(r"#define NMNIST_REF_SPIKES \d+", f"#define NMNIST_REF_SPIKES {nsp}", h2)
    h2 = re.sub(r"static const uint8_t EVENTS\[\d+\] = \{[^}]*\};", f"static const uint8_t EVENTS[{len(ev)}] = {{ {', '.join(str(int(x)) for x in ev)} }};", h2)
    h2 = re.sub(r"static const int32_t REF_O\[\d+\] = \{[^}]*\};", f"static const int32_t REF_O[{out}] = {{ {', '.join(str(int(x)) for x in o)} }};", h2)
    a.dst.mkdir(parents=True, exist_ok=True)
    (a.dst / "weights.h").write_text(h2)
    cyc = (a.src / "events.hex").read_text().split()[:a.events]
    (a.dst / "events.hex").write_text("\n".join(cyc) + "\n")
    (a.dst / "events.vh").write_text(f"// trimmed copy: first {len(ev)} events of {a.src}\nlocalparam integer N_EV = {len(ev)};\n")
    print(f"wrote {a.dst}: {len(ev)} events, {nsp} hidden spikes, decision at event {dec}, ref o {o.tolist()}")


if __name__ == "__main__":
    main()
