#!/usr/bin/env python3
"""Patch SRAM22 macro views for OpenLane / Magics / PDN.

Fixes:
1. GDS: ensure top cell has prBoundary 235/4 matching LEF SIZE (Magics FIXED_BBOX).
2. LEF: remove full-macro met2 OBS that blocked PDN vias to vdd/vss on met2.
   Keep met1 OBS; do not OBS met3/met4/met5 so the via stack can land.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def patch_lef(lef_path: Path, backup: bool = True) -> None:
    text = lef_path.read_text()
    if backup:
        bak = lef_path.with_suffix(lef_path.suffix + ".pre_pdn_fix")
        if not bak.exists():
            bak.write_text(text)

    # Replace OBS block: drop met2 full cover (power pins are on met2).
    new_obs = """OBS
        LAYER met1 ;
            RECT 0.000 0.000 674.480 781.920 ;
    END"""
    text2, n = re.subn(
        r"OBS\s*?LAYER met1\s*;\s*RECT[^;]+;\s*LAYER met2\s*;\s*RECT[^;]+;\s*END",
        new_obs,
        text,
        count=1,
        flags=re.S,
    )
    if n != 1:
        # Already patched or unexpected format
        if "LAYER met2" in text[text.find("OBS") : text.find("OBS") + 200]:
            raise SystemExit(f"Failed to patch OBS in {lef_path}")
        print(f"LEF OBS already looks patched: {lef_path}")
        return
    lef_path.write_text(text2)
    print(f"Patched LEF OBS (removed met2 blockage): {lef_path}")


def write_klayout_prboundary_script(script: Path, gds_in: Path, gds_out: Path, cell: str, w_um: float, h_um: float) -> None:
    script.write_text(
        f"""
import pya
gds_in = {str(gds_in)!r}
gds_out = {str(gds_out)!r}
cell_name = {cell!r}
w_um = {w_um}
h_um = {h_um}

layout = pya.Layout()
layout.read(gds_in)
top = None
for c in layout.each_cell():
    if c.name == cell_name:
        top = c
        break
if top is None:
    top = layout.top_cell()
    print("WARN: using top_cell", top.name)

# sky130 Magics prBoundary
layer = layout.layer(pya.LayerInfo(235, 4))
# Clear existing 235/4 on top only (keep hierarchy copies elsewhere)
top.shapes(layer).clear()
# LEF SIZE is in microns; layout.dbu is um per database unit (e.g. 0.001)
dbu = layout.dbu
box = pya.DBox(0.0, 0.0, w_um, h_um)
top.shapes(layer).insert(box.to_itype(dbu))
print("Inserted 235/4 on", top.name, "box_um", box, "dbu", dbu)
layout.write(gds_out)
print("Wrote", gds_out)
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--macros-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "sky130_vex2_soc/macros",
    )
    ap.add_argument("--cell", default="sram22_2048x32m8w8")
    ap.add_argument("--width", type=float, default=674.480)
    ap.add_argument("--height", type=float, default=781.920)
    args = ap.parse_args()

    lef = args.macros_dir / f"{args.cell}.lef"
    gds = args.macros_dir / f"{args.cell}.gds"
    if not lef.exists() or not gds.exists():
        raise SystemExit(f"missing {lef} or {gds}")

    patch_lef(lef)

    gds_bak = gds.with_suffix(".gds.pre_prboundary")
    if not gds_bak.exists():
        shutil.copy2(gds, gds_bak)
        print(f"Backed up GDS to {gds_bak}")

    script = args.macros_dir / "_patch_prboundary.py"
    gds_tmp = args.macros_dir / f"{args.cell}.prboundary.gds"
    write_klayout_prboundary_script(script, gds_bak if gds_bak.exists() else gds, gds_tmp, args.cell, args.width, args.height)
    print(f"KLayout script: {script}")
    print(f"Run: klayout -b -r {script}  &&  mv {gds_tmp} {gds}")


if __name__ == "__main__":
    main()
