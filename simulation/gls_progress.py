#!/usr/bin/env python3
"""Run vvp for GLS with a live progress UI.

Phases:
  1) SDF annotate (if --sdf-log): elapsed spinner until TB prints past annotate
  2) Simulation: cycle bar from GLS_PROGRESS lines (and milestone echoes)

Usage:
  python3 gls_progress.py [--sdf-log PATH] [--timeout-cycles N] -- vvp <args...>
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path


PROG_RE = re.compile(r"GLS_PROGRESS\s+cycle=(\d+)(?:\s+max=(\d+))?")
DONE_HINTS = (
    "SDF: annotated",
    "TB: reset released",
    "PASS:",
    "FAIL:",
)


def _bar(frac: float, width: int = 28) -> str:
    frac = max(0.0, min(1.0, frac))
    fill = int(width * frac)
    return "#" * fill + "-" * (width - fill)


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds > 24 * 3600:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


class Ui:
    def __init__(self, timeout_cycles: int) -> None:
        self.timeout_cycles = max(timeout_cycles, 1)
        self.phase = "start"
        self.t0 = time.monotonic()
        self.sdf_t0: float | None = None
        self.sim_t0: float | None = None
        self.cycle = 0
        self.last_draw = 0.0
        self.lock = threading.Lock()
        self.alive = True

    def set_phase(self, phase: str) -> None:
        with self.lock:
            if phase == self.phase:
                return
            self.phase = phase
            now = time.monotonic()
            if phase == "sdf" and self.sdf_t0 is None:
                self.sdf_t0 = now
            if phase == "sim" and self.sim_t0 is None:
                self.sim_t0 = now
            self._draw(force=True)

    def set_cycle(self, cycle: int, vmax: int | None = None) -> None:
        with self.lock:
            self.cycle = cycle
            if vmax and vmax > 0:
                self.timeout_cycles = vmax
            if self.phase != "sim":
                self.phase = "sim"
                if self.sim_t0 is None:
                    self.sim_t0 = time.monotonic()
            self._draw()

    def tick(self) -> None:
        with self.lock:
            self._draw()

    def finish(self, ok: bool) -> None:
        with self.lock:
            self.alive = False
            elapsed = time.monotonic() - self.t0
            status = "done" if ok else "FAILED"
            print(
                f"\r  GLS {status} in {_fmt_eta(elapsed)} ({elapsed:.1f}s)"
                + " " * 40,
                file=sys.stderr,
            )
            print(file=sys.stderr)

    def _draw(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self.last_draw) < 0.2:
            return
        self.last_draw = now
        if self.phase == "sdf":
            dt = now - (self.sdf_t0 or self.t0)
            spin = "|/-\\" [int(dt * 4) % 4]
            # Icarus is silent until $sdf_annotate returns; no % available.
            msg = (
                f"\r  [{spin}] SDF annotate (CPU-bound, often 5–20+ min; "
                f"no % until done)  {_fmt_eta(dt)} ({dt:.0f}s)   "
            )
        elif self.phase == "sim":
            vmax = self.timeout_cycles
            frac = min(1.0, self.cycle / vmax)
            dt = now - (self.sim_t0 or self.t0)
            rate = self.cycle / dt if dt > 0.5 and self.cycle > 0 else 0.0
            remain = (vmax - self.cycle) / rate if rate > 0 else -1.0
            msg = (
                f"\r  [{_bar(frac)}] sim {100 * frac:5.1f}%  "
                f"cycle {self.cycle}/{vmax}  "
                f"{rate:.0f} cyc/s  ETA {_fmt_eta(remain)}   "
            )
        else:
            msg = f"\r  [.] GLS starting…   "
        print(msg, end="", file=sys.stderr, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdf-log", type=Path, default=None)
    ap.add_argument("--timeout-cycles", type=int, default=5_000_000)
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="command after --")
    args = ap.parse_args()
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("ERROR: missing vvp command", file=sys.stderr)
        return 2

    ui = Ui(args.timeout_cycles)
    if args.sdf_log is not None:
        ui.set_phase("sdf")
        args.sdf_log.parent.mkdir(parents=True, exist_ok=True)
        args.sdf_log.write_text("")  # truncate
    else:
        ui.set_phase("sim")

    stderr_f = open(args.sdf_log, "w", buffering=1) if args.sdf_log else subprocess.DEVNULL

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=stderr_f,
        text=True,
        bufsize=1,
    )

    stop_tick = threading.Event()

    def ticker() -> None:
        while not stop_tick.wait(0.25):
            ui.tick()

    th = threading.Thread(target=ticker, daemon=True)
    th.start()

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            m = PROG_RE.search(line)
            if m:
                cyc = int(m.group(1))
                mx = int(m.group(2)) if m.group(2) else None
                ui.set_cycle(cyc, mx)
                continue
            # Pass through TB / PASS / FAIL (Icarus prints SDF ERROR on stdout)
            if line.strip():
                if args.sdf_log is not None and (
                    "SDF ERROR" in line
                    or "VPI error" in line
                    or line.startswith("SDF:")
                ):
                    try:
                        with args.sdf_log.open("a") as lf:
                            lf.write(line + "\n")
                    except OSError:
                        pass
                # Leave progress line, print message, restore bar next tick
                print(f"\r{' ' * 90}\r{line}", flush=True)
                if any(h in line for h in DONE_HINTS):
                    if "SDF: annotated" in line or "TB: reset" in line:
                        ui.set_phase("sim")
    finally:
        stop_tick.set()
        rc = proc.wait()
        if isinstance(stderr_f, type(sys.stderr)):
            pass
        elif hasattr(stderr_f, "close"):
            stderr_f.close()
        ui.finish(rc == 0)
    return rc


if __name__ == "__main__":
    sys.exit(main())
