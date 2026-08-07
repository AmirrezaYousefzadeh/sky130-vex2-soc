#!/usr/bin/env python3
"""Render a floorplan PNG from an OpenLane/OpenROAD DEF (viewable in Cursor)."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def parse_def(path: Path):
    text = path.read_text(errors="ignore")
    m = re.search(r"UNITS DISTANCE MICRONS\s+(\d+)", text)
    units = int(m.group(1)) if m else 1000

    m = re.search(
        r"DIEAREA\s+\(\s*([-\d]+)\s+([-\d]+)\s*\)\s*\(\s*([-\d]+)\s+([-\d]+)\s*\)",
        text,
    )
    if not m:
        raise SystemExit(f"No DIEAREA in {path}")
    die = tuple(int(x) / units for x in m.groups())

    pat = re.compile(
        r"-\s+(\S+)\s+(\S+)\s+\+\s+(?:FIXED|COVER|PLACED)\s+"
        r"\(\s*([-\d]+)\s+([-\d]+)\s*\)\s+(\S+)"
    )
    macros = []
    cells_x: list[float] = []
    cells_y: list[float] = []
    for name, cell, x, y, ori in pat.findall(text):
        xu, yu = int(x) / units, int(y) / units
        if "sram" in cell.lower():
            macros.append((name, cell, xu, yu, ori))
        else:
            cells_x.append(xu)
            cells_y.append(yu)
    return die, macros, cells_x, cells_y


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
    die, macros, cx, cy = parse_def(def_file)
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
    ax.set_title(
        f"{title}\n{def_file.name} — {len(macros)} macros, {len(cx)} placed cells"
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
    print(f"  placed std-cells: {len(cx)}")


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
