#!/usr/bin/env python3
"""Rewrite a VCD so timestamps are in 1ns instead of 1ps (divide by 1000).

Icarus often emits $timescale 1ps because RTL/PDK use `timescale 1ns/1ps.
Viewers then show huge picosecond counters; this makes the file read in ns.
No-op if the file is already in ns (or coarser).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _timescale_is_1ps(block: str) -> bool:
    # Collapse whitespace: "$timescale\n\t1ps\n$end" / "$timescale 1ps $end"
    body = " ".join(block.replace("$timescale", "").replace("$end", "").split())
    return body.lower() in {"1ps", "1 ps"}


def rescale_file(path: Path) -> bool:
    tmp = path.with_suffix(path.suffix + ".tmp")
    changed = False
    with path.open("r", errors="replace") as fin, tmp.open("w") as fout:
        # Header through $enddefinitions
        while True:
            line = fin.readline()
            if not line:
                break
            if line.startswith("$timescale"):
                block = line
                while "$end" not in block:
                    nxt = fin.readline()
                    if not nxt:
                        break
                    block += nxt
                if _timescale_is_1ps(block):
                    fout.write("$timescale\n\t1ns\n$end\n")
                    changed = True
                else:
                    fout.write(block)
                continue
            fout.write(line)
            if line.startswith("$enddefinitions"):
                break

        if not changed:
            # Copy remainder unchanged, then discard tmp
            for line in fin:
                fout.write(line)
            fout.close()
            tmp.unlink(missing_ok=True)
            return False

        for line in fin:
            if line.startswith("#"):
                raw = line[1:].strip()
                if raw:
                    fout.write(f"#{int(raw) // 1000}\n")
                else:
                    fout.write(line)
            else:
                fout.write(line)

    tmp.replace(path)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("vcd", type=Path)
    args = ap.parse_args()
    if not args.vcd.is_file():
        print(f"ERROR: VCD not found: {args.vcd}", file=sys.stderr)
        return 1
    if rescale_file(args.vcd):
        print(f"VCD timescale: 1ps → 1ns ({args.vcd})")
    else:
        print(f"VCD timescale unchanged ({args.vcd})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
