#!/usr/bin/env python3
"""Render a floorplan PNG from an OpenLane/OpenROAD DEF (viewable in Cursor).

Streams the DEF line-by-line (fillinsertion DEFs can be 40MB+; loading the whole
file and running regex findall used to hang the synthesis wrapper).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

_COMPONENT_RE = re.compile(
    r"-\s+(\S+)\s+(\S+)\s+\+\s+(?:FIXED|COVER|PLACED)\s+"
    r"\(\s*([-\d]+)\s+([-\d]+)\s*\)\s+(\S+)"
)
_FILLER_HINTS = ("fill_", "decap", "tap", "diode", "filler")


def _is_filler(cell: str) -> bool:
    c = cell.lower()
    return any(h in c for h in _FILLER_HINTS)


def parse_def(path: Path):
    units = 1000
    die = None
    macros: list[tuple[str, str, float, float, str]] = []
    cells_x: list[float] = []
    cells_y: list[float] = []
    # Cap plotted stdcells so huge fillinsertion DEFs stay interactive.
    max_cells = 80_000
    skipped_fillers = 0

    with path.open(errors="ignore") as f:
        for line in f:
            if die is None and "DIEAREA" in line:
                m = re.search(
                    r"DIEAREA\s+\(\s*([-\d]+)\s+([-\d]+)\s*\)\s*\(\s*([-\d]+)\s+([-\d]+)\s*\)",
                    line,
                )
                if m:
                    die = tuple(int(x) / units for x in m.groups())
                continue
            if "UNITS DISTANCE MICRONS" in line:
                m = re.search(r"UNITS DISTANCE MICRONS\s+(\d+)", line)
                if m:
                    units = int(m.group(1))
                continue
            if not line.lstrip().startswith("-"):
                continue
            m = _COMPONENT_RE.search(line)
            if not m:
                continue
            name, cell, x, y, ori = m.groups()
            xu, yu = int(x) / units, int(y) / units
            if "sram" in cell.lower():
                macros.append((name, cell, xu, yu, ori))
            elif _is_filler(cell):
                skipped_fillers += 1
            elif len(cells_x) < max_cells:
                cells_x.append(xu)
                cells_y.append(yu)

    if die is None:
        raise SystemExit(f"No DIEAREA in {path}")
    return die, macros, cells_x, cells_y, skipped_fillers


def macro_size_um(lef: Path | None, default=(674.48, 781.92)):
    if lef and lef.exists():
        m = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", lef.read_text())
        if m:
            return float(m.group(1)), float(m.group(2))
    return default


def render(
    def_file: Path,
    output: Path,
    lef: Path | None,
    title: str,
) -> None:
    die, macros, cx, cy, skipped_fillers = parse_def(def_file)
    mw, mh = macro_size_um(lef)
    dx0, dy0, dx1, dy1 = die

    fig, ax = plt.subplots(figsize=(12, 9))
    ax.add_patch(
        Rectangle(
            (dx0, dy0),
            dx1 - dx0,
            dy1 - dy0,
            fill=False,
            lw=2,
            ec="black",
            label=f"DIE {dx1 - dx0:.0f}×{dy1 - dy0:.0f} µm",
        )
    )

    if cx:
        hb = ax.hexbin(
            cx, cy, gridsize=80, cmap="Greens", mincnt=1, linewidths=0, alpha=0.9
        )
        cb = fig.colorbar(hb, ax=ax, fraction=0.03, pad=0.02)
        cb.set_label("std-cell count / bin")

    colors = ["#4C78A8", "#F58518", "#E45756", "#72B7B2"]
    for i, (name, _cell, x, y, _ori) in enumerate(macros):
        ax.add_patch(
            Rectangle(
                (x, y),
                mw,
                mh,
                fc=colors[i % len(colors)],
                ec="black",
                alpha=0.85,
                label=name,
            )
        )
        ax.text(
            x + mw / 2,
            y + mh / 2,
            f"{name}\n({x:.0f},{y:.0f})",
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )

    ax.set_xlim(dx0 - 30, dx1 + 30)
    ax.set_ylim(dy0 - 30, dy1 + 30)
    ax.set_aspect("equal")
    ax.set_xlabel("µm")
    ax.set_ylabel("µm")
    extra = f", skipped {skipped_fillers} fillers" if skipped_fillers else ""
    ax.set_title(
        f"{title}\n{def_file.name} — {len(macros)} macros, {len(cx)} cells{extra}"
    )
    ax.grid(True, alpha=0.25)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(dict(zip(labels, handles)).values(), dict(zip(labels, handles)).keys(), loc="upper right")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)
    print(f"Wrote {output}")
    print(f"  DIE=({dx0:.0f},{dy0:.0f})-({dx1:.0f},{dy1:.0f}) µm")
    for name, _cell, x, y, _ori in macros:
        print(f"  {name} @ ({x:.1f}, {y:.1f})")
    print(f"  placed std-cells: {len(cx)}" + (f" (skipped {skipped_fillers} fillers)" if skipped_fillers else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("def_file", type=Path, help="Input .def from an OpenLane run")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output .png path")
    ap.add_argument("--lef", type=Path, default=None, help="Macro LEF (for SIZE)")
    ap.add_argument("--title", default="Floorplan from DEF")
    args = ap.parse_args()
    if not args.def_file.is_file():
        raise SystemExit(f"DEF not found: {args.def_file}")
    render(args.def_file, args.output, args.lef, args.title)


if __name__ == "__main__":
    main()
