#!/usr/bin/env python3
"""Build a publication-style timeline figure:

  clk | sleep of core | inference activity | total power

Defaults read the time-power outputs (windows.json + power_vs_time.csv),
which were produced from the GLS waveform VCD. Sleep follows per-window
``sram_clk_en`` duty (core ICG enable); inference is the longest awake span.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_power_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t0s: list[float] = []
    t1s: list[float] = []
    p_uW: list[float] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            t0s.append(float(row["t0"]))
            t1s.append(float(row["t1"]))
            p_uW.append(float(row["top_total_uW"]))
    return np.asarray(t0s), np.asarray(t1s), np.asarray(p_uW)


def sleep_from_windows(path: Path, duty_thresh: float = 0.5) -> tuple[list[tuple[int, int]], int]:
    """Build sleeping step history from windowed sram_clk_en duty."""
    meta = json.loads(path.read_text())
    t_end = int(meta["t_end"])
    hist: list[tuple[int, int]] = [(0, 0)]
    for w in meta["windows"]:
        duty = float(w["interesting"]["sram_clk_en"]["duty"])
        sleeping = 1 if duty < duty_thresh else 0
        t0 = int(w["t0"])
        if hist[-1][1] != sleeping:
            # Transition at window start.
            if t0 != hist[-1][0]:
                hist.append((t0, sleeping))
            else:
                hist[-1] = (t0, sleeping)
    return hist, t_end


def longest_high_interval(hist: list[tuple[int, int]], t_end: int) -> tuple[int, int]:
    best = (0, 0)
    cur_start: int | None = None
    for t, v in hist + [(t_end, 0)]:
        if v == 1 and cur_start is None:
            cur_start = t
        elif v == 0 and cur_start is not None:
            if t - cur_start > best[1] - best[0]:
                best = (cur_start, t)
            cur_start = None
    return best


def make_inference(sleeping: list[tuple[int, int]], t_end: int) -> list[tuple[int, int]]:
    awake = [(t, 1 - v) for t, v in sleeping]
    t0, t1 = longest_high_interval(awake, t_end)
    return [(0, 0), (t0, 1), (t1, 0)]


def steps_to_arrays(
    hist: list[tuple[int, int]], t_end: int
) -> tuple[np.ndarray, np.ndarray]:
    times = [t for t, _ in hist] + [t_end]
    vals = [v for _, v in hist] + [hist[-1][1]]
    return np.asarray(times, dtype=float), np.asarray(vals, dtype=float)


def digital_step_plot(ax, times, vals, *, color: str, y0: float = 0.08, y1: float = 0.92):
    yt = y0 + (y1 - y0) * vals
    ax.step(times, yt, where="post", color=color, lw=1.4)
    ax.fill_between(times, y0, yt, step="post", color=color, alpha=0.18)


def plot_timeline(
    *,
    sleep_hist: list[tuple[int, int]],
    t_end: int,
    t0s: np.ndarray,
    t1s: np.ndarray,
    power_uW: np.ndarray,
    out: Path,
    title: str,
) -> None:
    infer_hist = make_inference(sleep_hist, t_end)
    t_sleep, v_sleep = steps_to_arrays(sleep_hist, t_end)
    t_inf, v_inf = steps_to_arrays(infer_hist, t_end)
    t_us = 1e-3  # ns → µs

    fig, axes = plt.subplots(
        4,
        1,
        figsize=(10.5, 6.2),
        sharex=True,
        gridspec_kw={"height_ratios": [0.7, 0.7, 0.7, 1.6], "hspace": 0.08},
    )
    fig.patch.set_facecolor("white")

    # clk — always-on; real edges are µs-dense so show a schematic band.
    ax = axes[0]
    ax.set_ylim(-0.05, 1.15)
    period_us = max(t_end * t_us / 180.0, 0.5)
    xs = np.arange(0.0, t_end * t_us + period_us, period_us)
    ys = np.where((np.arange(len(xs)) % 2) == 0, 0.85, 0.15)
    ax.step(xs, ys, where="post", color="#2a6f97", lw=0.7, alpha=0.9)
    ax.fill_between(xs, 0.15, ys, step="post", color="#2a6f97", alpha=0.18)
    ax.set_ylabel("clk", rotation=0, ha="right", va="center", fontsize=10)
    ax.set_yticks([])
    ax.text(
        0.995,
        0.92,
        "always on",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color="#445",
    )

    ax = axes[1]
    ax.set_ylim(-0.05, 1.15)
    digital_step_plot(ax, t_sleep * t_us, v_sleep, color="#c1121f")
    ax.set_ylabel("sleep\nof core", rotation=0, ha="right", va="center", fontsize=10)
    ax.set_yticks([0.08, 0.92], ["0", "1"])

    ax = axes[2]
    ax.set_ylim(-0.05, 1.15)
    digital_step_plot(ax, t_inf * t_us, v_inf, color="#2d6a4f")
    ax.set_ylabel("inference\nactivity", rotation=0, ha="right", va="center", fontsize=10)
    ax.set_yticks([0.08, 0.92], ["0", "1"])

    ax = axes[3]
    # Stairstep matching power_vs_time.vcd windows.
    t_step = np.empty(2 * len(t0s), dtype=float)
    p_step = np.empty(2 * len(power_uW), dtype=float)
    t_step[0::2] = t0s
    t_step[1::2] = t1s
    p_step[0::2] = power_uW
    p_step[1::2] = power_uW
    ax.plot(t_step * t_us, p_step, color="#1b4332", lw=1.1)
    ax.fill_between(t_step * t_us, 0, p_step, color="#1b4332", alpha=0.18)
    ax.set_ylabel("total power\n(µW)", rotation=0, ha="right", va="center", fontsize=10)
    ax.set_xlabel("time (µs)")
    ax.set_ylim(0, max(float(power_uW.max()) * 1.08, 1.0))
    ax.grid(True, axis="y", alpha=0.25, lw=0.6)

    for a in axes:
        a.spines["top"].set_visible(False)
        a.spines["right"].set_visible(False)
        a.set_xlim(0, t_end * t_us)

    fig.suptitle(title, fontsize=12, y=0.98)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.93, bottom=0.09)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    fig.savefig(out.with_suffix(".pdf"))
    plt.close(fig)
    _progress(f"wrote {out}")
    _progress(f"wrote {out.with_suffix('.pdf')}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    default_out_dir = Path(__file__).resolve().parent / "out_waveform_gls_time"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--windows-json",
        type=Path,
        default=default_out_dir / "windows.json",
        help="Windowed activity from vcd_to_windows.py (GLS VCD)",
    )
    ap.add_argument(
        "--power-csv",
        type=Path,
        default=default_out_dir / "power_vs_time.csv",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=root / "docs" / "figures" / "power_timeline.png",
    )
    ap.add_argument(
        "--title",
        default="sky130 VexRiscv SoC — sleep / MNIST inference / time-based power",
    )
    args = ap.parse_args()

    if not args.windows_json.is_file():
        raise SystemExit(f"missing windows.json: {args.windows_json}")
    if not args.power_csv.is_file():
        raise SystemExit(f"missing power CSV: {args.power_csv}")

    _progress(f"sleep/inference from {args.windows_json}")
    sleep_hist, t_end = sleep_from_windows(args.windows_json)
    _progress(f"power from {args.power_csv}")
    t0s, t1s, power_uW = load_power_csv(args.power_csv)
    plot_timeline(
        sleep_hist=sleep_hist,
        t_end=t_end,
        t0s=t0s,
        t1s=t1s,
        power_uW=power_uW,
        out=args.out,
        title=args.title,
    )


if __name__ == "__main__":
    main()
