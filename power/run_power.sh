#!/usr/bin/env bash
# Activity-based power + energy from a VCD + post-PnR netlist/SPEF.
#
# Usage:
#   ./power/run_power.sh path/to/file.vcd
#   ./power/run_power.sh                          # default: simulation/mnist_mlp.vcd
#
# Env:
#   VCD=path                 input waveform
#   RUN_DIR=path             OpenLane run with final/nl + final/spef
#   DESIGN_PERIOD_NS=40      ASIC clock period for power (match CLOCK_PERIOD)
#   OUT=path                 output directory (default power/out_<name>)
#   SCOPE=tb_fw_mnist.u_soc  VCD hierarchy to sample
#   PDK_ROOT / OPENLANE_ROOT
#
# Writes:
#   OUT/power_energy.txt     human-readable power + energy summary
#   OUT/power_activity.rpt   OpenSTA report_power
#   OUT/activity.json        extracted toggle rates
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POWER="$(cd "$(dirname "$0")" && pwd)"
export ROOT
export PDK_ROOT="${PDK_ROOT:-/media/pdk}"
OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"

if [[ $# -ge 1 ]]; then
  VCD="$1"
else
  VCD="${VCD:-$ROOT/simulation/mnist_mlp.vcd}"
fi

RUN_DIR="${RUN_DIR:-$ROOT/hardening/sky130_vex2_soc/runs/sky130_vex2_soc_v2}"
DESIGN_PERIOD_NS="${DESIGN_PERIOD_NS:-40}"
SCOPE="${SCOPE:-tb_fw_mnist.u_soc}"
base="$(basename "$VCD" .vcd)"
OUT="${OUT:-$POWER/out_${base}}"
ACT_JSON="$OUT/activity.json"
ACT_TCL="$OUT/activity.tcl"

if [[ ! -f "$VCD" ]]; then
  echo "ERROR: VCD not found: $VCD" >&2
  echo "Generate one with: ./simulation/run_sim.sh fw --vcd" >&2
  exit 1
fi
if [[ ! -d "$RUN_DIR/final" ]]; then
  echo "ERROR: OpenLane run final/ missing: $RUN_DIR" >&2
  echo "Set RUN_DIR to a completed hardening run." >&2
  exit 1
fi

mkdir -p "$OUT"

echo "==> Extracting activity from $VCD"
python3 "$POWER/vcd_to_activity.py" "$VCD" \
  --scope "$SCOPE" \
  --design-period-ns "$DESIGN_PERIOD_NS" \
  -o "$ACT_JSON" \
  --sta-tcl "$ACT_TCL"

export RUN_DIR POWER_OUT="$OUT" ACTIVITY_TCL="$ACT_TCL"
export LIB_SC="$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
export LIB_SRAM="$ROOT/hardening/sky130_vex2_soc/macros/sram22_2048x32m8w8_tt_025C_1v80.lib"

echo "==> OpenSTA activity-based power (period=${DESIGN_PERIOD_NS} ns)"
cd "$ROOT"
nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config \
  "$OL2" -c \
  sta -no_splash -exit "$POWER/power_activity_sta.tcl"

python3 "$POWER/summarize_energy.py" \
  --activity-json "$ACT_JSON" \
  --power-rpt "$OUT/power_activity.rpt" \
  --design-period-ns "$DESIGN_PERIOD_NS" \
  -o "$OUT/power_energy.txt"

echo
echo "Reports:"
echo "  $OUT/power_energy.txt"
echo "  $OUT/power_activity.rpt"
echo "  $OUT/activity.json"
echo
cat "$OUT/power_energy.txt"
