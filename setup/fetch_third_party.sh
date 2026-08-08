#!/usr/bin/env bash
# Clone third-party sources used by this project (VexRiscv generator + SRAM22 macros).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TP="$ROOT/third_party"
mkdir -p "$TP"

clone_or_update() {
  local url="$1" dest="$2"
  if [[ -d "$dest/.git" ]]; then
    echo "Already present: $dest"
  else
    git clone --depth 1 "$url" "$dest"
  fi
}

clone_or_update https://github.com/SpinalHDL/VexRiscv.git "$TP/VexRiscv"
clone_or_update https://github.com/ucb-bar/sram22_sky130_macros.git "$TP/sram22_sky130_macros"

# Behavioral SRAM model link for RTL sim
mkdir -p "$ROOT/rtl/sram"
CELL=sram22_2048x32m8w8
SRC="$TP/sram22_sky130_macros/${CELL}/${CELL}.v"
if [[ -f "$SRC" ]]; then
  ln -sfn "../../third_party/sram22_sky130_macros/${CELL}/${CELL}.v" \
    "$ROOT/rtl/sram/${CELL}.v"
  echo "Linked rtl/sram/${CELL}.v"
fi

echo "Done. For OpenLane macros, copy/patch views into synthesis/sky130_vex2_soc/macros/"
echo "  (see synthesis/scripts/fix_sram22_macro.sh)"
