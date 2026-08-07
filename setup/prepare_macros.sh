#!/usr/bin/env bash
# Copy SRAM22 views into hardening/.../macros and apply LEF/GDS patches.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CELL=sram22_2048x32m8w8
SRC="$ROOT/third_party/sram22_sky130_macros/$CELL"
DST="$ROOT/hardening/sky130_vex2_soc/macros"

if [[ ! -d "$SRC" ]]; then
  echo "ERROR: missing $SRC — run ./setup/fetch_third_party.sh first" >&2
  exit 1
fi

mkdir -p "$DST"
echo "Copying $CELL views → $DST"
cp -f "$SRC/${CELL}.lef" "$DST/"
cp -f "$SRC/${CELL}_tt_025C_1v80.lib" "$DST/"
cp -f "$SRC/${CELL}_ss_100C_1v60.lib" "$DST/"
cp -f "$SRC/${CELL}_ff_n40C_1v95.lib" "$DST/"
cp -f "$SRC/${CELL}.v" "$DST/${CELL}.bb.v" 2>/dev/null || true

if [[ -f "$SRC/${CELL}.gds.gz" ]]; then
  echo "Unpacking GDS…"
  gzip -dc "$SRC/${CELL}.gds.gz" > "$DST/${CELL}.gds"
elif [[ -f "$SRC/${CELL}.gds" ]]; then
  cp -f "$SRC/${CELL}.gds" "$DST/"
fi

echo "Patching macro for OpenLane/Magic PR-boundary + PDN…"
bash "$ROOT/hardening/scripts/fix_sram22_macro.sh"
echo "Done."
