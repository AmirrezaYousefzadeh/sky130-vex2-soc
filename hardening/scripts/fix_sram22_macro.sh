#!/usr/bin/env bash
# Patch SRAM22 LEF/GDS for Magics PR-boundary + PDN met2 access, then smoke-test Magics bbox.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"
MACROS="$ROOT/hardening/sky130_vex2_soc/macros"
CELL=sram22_2048x32m8w8
export PDK_ROOT="${PDK_ROOT:-/media/pdk}"

python3 "$ROOT/hardening/scripts/fix_sram22_macro.py" --macros-dir "$MACROS" --cell "$CELL"

run_nix() {
  nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config "$OL2" -c "$@"
}

run_nix klayout -b -r "$MACROS/_patch_prboundary.py"
mv -f "$MACROS/${CELL}.prboundary.gds" "$MACROS/${CELL}.gds"
echo "Updated $MACROS/${CELL}.gds"

VERIFY_PY="$MACROS/_verify_prboundary.py"
cat >"$VERIFY_PY" <<PY
import pya
layout = pya.Layout()
layout.read("$MACROS/${CELL}.gds")
top = None
for c in layout.each_cell():
    if c.name == "$CELL":
        top = c
        break
print("top", top.name)
li = layout.layer(pya.LayerInfo(235, 4))
print("235/4 shapes on top", top.shapes(li).size())
for s in top.shapes(li).each():
    print(" box_um", s.dbox)
if top.shapes(li).size() < 1:
    raise SystemExit("missing 235/4 on top")
PY
run_nix klayout -b -r "$VERIFY_PY"

# Magics FULL macro GDS load is very slow; prove 235/4→FIXED_BBOX on a tiny GDS.
TINY_PY="$MACROS/_tiny_prb.py"
cat >"$TINY_PY" <<'PY'
import pya
layout = pya.Layout()
layout.dbu = 0.001
cell = layout.create_cell("sram22_prb_test")
li = layout.layer(pya.LayerInfo(235, 4))
cell.shapes(li).insert(pya.DBox(0, 0, 674.48, 781.92).to_itype(layout.dbu))
layout.write("$ROOT/hardening/sky130_vex2_soc/macros/_tiny_prb.gds")
PY
# path baked above — rewrite with MACROS
cat >"$TINY_PY" <<PY
import pya
layout = pya.Layout()
layout.dbu = 0.001
cell = layout.create_cell("sram22_prb_test")
li = layout.layer(pya.LayerInfo(235, 4))
cell.shapes(li).insert(pya.DBox(0, 0, 674.48, 781.92).to_itype(layout.dbu))
layout.write(r"$MACROS/_tiny_prb.gds")
print("wrote tiny prboundary gds")
PY
run_nix klayout -b -r "$TINY_PY"

MAGICRC="$PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc"
BBOX_LOG="$MACROS/${CELL}.get_bbox_test.log"
BBOX_TCL="$MACROS/_get_bbox_test.tcl"
cat >"$BBOX_TCL" <<EOF
gds read $MACROS/_tiny_prb.gds
load sram22_prb_test
foreach property [property] {
  if {[lindex \$property 0] == "FIXED_BBOX"} {
    puts "FIXED_BBOX [lindex \$property 1] [lindex \$property 2] [lindex \$property 3] [lindex \$property 4]"
  }
}
quit -noprompt
EOF

run_nix magic -dnull -noconsole -rcfile "$MAGICRC" "$BBOX_TCL" | tee "$BBOX_LOG"

if rg -q "FIXED_BBOX" "$BBOX_LOG"; then
  echo "PASS: Magics maps 235/4 → FIXED_BBOX (same layer inserted on full macro GDS)"
else
  echo "FAIL: Magics still missing FIXED_BBOX — see $BBOX_LOG"
  exit 1
fi
