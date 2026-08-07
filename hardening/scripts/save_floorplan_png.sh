#!/usr/bin/env bash
# Save a real floorplan PNG from the latest (or chosen) OpenLane DEF.
#
# Usage:
#   ./scripts/save_floorplan_png.sh
#   ./scripts/save_floorplan_png.sh path/to/design.def
#   OUT=my_floorplan.png ./scripts/save_floorplan_png.sh
#
# Output defaults to: hardening/sky130_vex2_soc/floorplan_real.png
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESIGN_DIR="$ROOT/hardening/sky130_vex2_soc"
RUNS="$DESIGN_DIR/runs"
LEF="$DESIGN_DIR/macros/sram22_2048x32m8w8.lef"
OUT="${OUT:-$DESIGN_DIR/floorplan_real.png}"
PY="$ROOT/hardening/scripts/plot_floorplan_def.py"

pick_python() {
  if [[ -x /media/hardware_design_tools/venv/bin/python ]]; then
    echo /media/hardware_design_tools/venv/bin/python
  else
    echo python3
  fi
}

# Prefer a DEF that already has std-cell placement (richest view).
find_best_def() {
  local run_dir="$1"
  local candidates=(
    "$run_dir"/47-openroad-fillinsertion/*.def
    "$run_dir"/39-openroad-detailedrouting/*.def
    "$run_dir"/29-openroad-detailedplacement/*.def
    "$run_dir"/23-openroad-globalplacement/*.def
    "$run_dir"/12-odb-manualmacroplacement/*.def
    "$run_dir"/09-openroad-floorplan/*.def
  )
  local f
  for f in "${candidates[@]}"; do
    # glob may stay literal if missing
    [[ -f "$f" ]] && { echo "$f"; return 0; }
  done
  # fallback: newest def in run
  find "$run_dir" -name '*.def' -type f -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | head -1 | cut -d' ' -f2-
}

DEF_FILE="${1:-}"

if [[ -z "$DEF_FILE" ]]; then
  if [[ ! -d "$RUNS" ]]; then
    echo "No runs directory: $RUNS"
    echo "Pass a .def explicitly, or run harden first."
    exit 1
  fi
  # Newest run directory
  LATEST_RUN="$(find "$RUNS" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
  if [[ -z "$LATEST_RUN" ]]; then
    echo "No OpenLane runs found under $RUNS"
    exit 1
  fi
  DEF_FILE="$(find_best_def "$LATEST_RUN")"
  if [[ -z "$DEF_FILE" || ! -f "$DEF_FILE" ]]; then
    echo "No .def found in $LATEST_RUN"
    exit 1
  fi
  echo "Using latest run: $(basename "$LATEST_RUN")"
fi

if [[ ! -f "$DEF_FILE" ]]; then
  echo "DEF not found: $DEF_FILE"
  exit 1
fi

PYTHON="$(pick_python)"
# Install matplotlib into shared venv if needed
if ! "$PYTHON" -c 'import matplotlib' 2>/dev/null; then
  echo "Installing matplotlib…"
  "$PYTHON" -m pip install -q matplotlib
fi

TITLE="sky130_vex2_soc — floorplan ($(basename "$(dirname "$DEF_FILE")"))"
LEF_ARGS=()
[[ -f "$LEF" ]] && LEF_ARGS=(--lef "$LEF")

echo "DEF: $DEF_FILE"
echo "OUT: $OUT"
"$PYTHON" "$PY" "$DEF_FILE" -o "$OUT" --title "$TITLE" "${LEF_ARGS[@]}"
echo "Open in Cursor: $OUT"
