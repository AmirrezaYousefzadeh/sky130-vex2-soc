#!/usr/bin/env python3
"""Sanitize OpenLane SDF for Icarus Verilog GLS.

Icarus struggles with OpenLane SDF enough that annotation aborts ("Too many
errors"), leaving the design without delays or in a bad state. This emits an
Icarus-friendly subset:

  - Fix VOLTAGE/TEMPERATURE/PROCESS ``min::max`` → ``min:typ:max``
  - Drop all INTERCONNECT (macro bit-selects / antenna paths break intermodpath)
  - Drop all TIMINGCHECK blocks (Icarus does not enforce them anyway)
  - Unwrap ``(COND ...)(IOPATH ...)`` → plain ``(IOPATH ...)`` (COND exprs with
    ``&`` / ``!`` confuse Icarus)
  - Drop IOPATHs with bit-selects (``dout[0]`` etc.; SRAM macros abort parse)
  - Drop empty DELAY/ABSOLUTE cells (e.g. top-level / macros after filtering)
  - Rewrite flattened INSTANCE names: OpenROAD ``u_foo\\.u_bar`` → Verilog
    escaped ``\\u_foo.u_bar`` (matches netlist cells; otherwise Icarus reports
    ``Cannot find u_foo``)

Keeps stdcell IOPATH delays so combo skew / glitches are still modeled.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# OpenROAD escape for '.' inside a flattened instance leaf name.
_INSTANCE_FLAT = re.compile(
    r"(\(INSTANCE\s+)((?:[A-Za-z_][A-Za-z0-9_$]*\\.)+[A-Za-z_][A-Za-z0-9_$]*)(\s*\))"
)


def _fix_flat_instance(line: str) -> tuple[str, bool]:
    """Map ``(INSTANCE a\\.b)`` → ``(INSTANCE \\a.b )`` for Icarus."""

    def repl(m: re.Match[str]) -> str:
        path = m.group(2).replace("\\.", ".")
        # Trailing space terminates the Verilog escaped identifier.
        return f"{m.group(1)}\\{path} {m.group(3).lstrip()}"

    new, n = _INSTANCE_FLAT.subn(repl, line)
    return new, n > 0


def _fix_header(line: str) -> str:
    if "VOLTAGE" in line or "TEMPERATURE" in line or "PROCESS" in line:
        line = re.sub(
            r"([-+0-9.eE]+)::([-+0-9.eE]+)",
            r"\1:\1:\2",
            line,
        )
    return line


def _skip_balanced(lines: list[str], start: int, open_ch: str = "(", close_ch: str = ")") -> int:
    """Return index just past the balanced block starting at lines[start]."""
    depth = 0
    i = start
    while i < len(lines):
        for ch in lines[i]:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(lines)


def sanitize(src: Path, dst: Path) -> dict[str, int]:
    raw = src.read_text(errors="replace").splitlines(keepends=True)
    stats = {
        "header_fixes": 0,
        "dropped_interconnect": 0,
        "dropped_timingcheck": 0,
        "unwrapped_cond": 0,
        "dropped_bitselect_iopath": 0,
        "dropped_empty_cells": 0,
        "fixed_flat_instances": 0,
    }

    # Pass 1: line filters + TIMINGCHECK block skip + COND unwrap
    out: list[str] = []
    i = 0
    while i < len(raw):
        line = raw[i]
        stripped = line.lstrip()

        if "VOLTAGE" in line or "TEMPERATURE" in line or "PROCESS" in line:
            fixed = _fix_header(line)
            if fixed != line:
                stats["header_fixes"] += 1
            line = fixed
            stripped = line.lstrip()

        if "\\." in line and stripped.startswith("(INSTANCE"):
            fixed, did = _fix_flat_instance(line)
            if did:
                stats["fixed_flat_instances"] += 1
                line = fixed
                stripped = line.lstrip()

        if stripped.startswith("(INTERCONNECT"):
            stats["dropped_interconnect"] += 1
            i += 1
            continue

        if stripped.startswith("(TIMINGCHECK"):
            stats["dropped_timingcheck"] += 1
            i = _skip_balanced(raw, i)
            continue

        if stripped.startswith("(COND"):
            # Skip COND line; keep following IOPATH with one fewer trailing ')'
            i += 1
            if i >= len(raw):
                break
            iopath = raw[i]
            # Strip one closing paren that belonged to COND (last ')')
            # Typical: "     (IOPATH ... ))\n"  or "...)))\n"
            nl = "\n" if iopath.endswith("\n") else ""
            body = iopath.rstrip("\n").rstrip()
            if body.endswith(")"):
                body = body[:-1].rstrip()
            # Bit-select ports (e.g. dout[0]) abort Icarus parse — drop them.
            if "[" in body:
                stats["dropped_bitselect_iopath"] += 1
                i += 1
                continue
            out.append(body + nl)
            stats["unwrapped_cond"] += 1
            i += 1
            continue

        if stripped.startswith("(IOPATH") and "[" in stripped:
            stats["dropped_bitselect_iopath"] += 1
            i += 1
            continue

        out.append(line)
        i += 1

    # Pass 2: drop CELL blocks with no remaining IOPATH
    text = "".join(out)
    final: list[str] = []
    first = text.find("(CELL")
    if first < 0:
        dst.write_text(text)
        return stats
    final.append(text[:first])
    rest = text[first:]
    parts = re.split(r"(?=\(CELL\b)", rest)
    for part in parts:
        if not part.strip():
            continue
        if not part.lstrip().startswith("(CELL"):
            final.append(part)
            continue
        if "(IOPATH" in part:
            final.append(part)
        else:
            stats["dropped_empty_cells"] += 1

    body = "".join(final)
    if not body.rstrip().endswith(")"):
        body = body.rstrip() + "\n)\n"

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    if not args.src.is_file():
        print(f"ERROR: SDF not found: {args.src}")
        return 1
    stats = sanitize(args.src, args.out)
    print(f"wrote {args.out}")
    for k, v in stats.items():
        print(f"  {k}={v}")
    print(f"  size={args.out.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
