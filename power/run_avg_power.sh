#!/usr/bin/env bash
# Activity-based power + energy from a VCD + post-PnR netlist/SPEF.
#
# Prefer a gate-level VCD (names match the netlist). RTL VCD still works but
# unmatched nets fall back to a median activity.
#
# Clock tree: OpenSTA derives activity from create_clock + set_propagated_clock
# (cannot set_power_activity on clock ports). Matching liberty + period matter.
# Sleep: core ICG GATE is case-analyzed from VCD sram_clk_en duty; average power
# blends awake/sleep reports (see power_icg_utils.tcl / summarize_energy.py).
#
# Usage:
#   ./power/run_avg_power.sh path/to/file.vcd
#   ./run_avg_power.sh ../simulation/waveform_gls.vcd
#   ./power/run_avg_power.sh                      # prefer simulation/waveform_gls.vcd
#
# Env:
#   VCD=path                 input waveform
#   RUN_DIR=path             OpenLane run with final/nl + final/spef
#   DESIGN_PERIOD_NS=N       ASIC clock for power (default: config.yaml CLOCK_PERIOD)
#   STD_CELL_LIBRARY=name    Override (else config.yaml / netlist sniff)
#   OUT=path                 output directory (default power/out_<name>)
#   SCOPE=tb_fw_mnist.u_soc  VCD hierarchy to sample
#   SKIP_CLEAN=1             keep previous OUT contents
#   PDK_ROOT / OPENLANE_ROOT
#
# Writes:
#   OUT/power_energy.txt     human-readable power + energy summary
#   OUT/power_activity.rpt   Full OpenSTA report_power
#   OUT/power_clock_tree.rpt Power of *clkbuf*/clkinv/clkdly* instances
#   OUT/activity.json        extracted toggle rates
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POWER="$(cd "$(dirname "$0")" && pwd)"
DES="$ROOT/synthesis/sky130_vex2_soc"
CFG="${CFG:-$DES/config.yaml}"
export ROOT
export PDK_ROOT="${PDK_ROOT:-/media/pdk}"
OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"
SKIP_CLEAN="${SKIP_CLEAN:-0}"

if [[ $# -ge 1 ]]; then
  VCD="$1"
else
  if [[ -n "${VCD:-}" ]]; then
    :
  elif [[ -f "$ROOT/simulation/waveform_gls.vcd" ]]; then
    VCD="$ROOT/simulation/waveform_gls.vcd"
  else
    VCD="$ROOT/simulation/waveform.vcd"
  fi
fi

# Match synthesis default run tag.
RUN_DIR="${RUN_DIR:-$DES/runs/sky130_vex2_soc}"
SCOPE="${SCOPE:-tb_fw_mnist.u_soc}"
base="$(basename "$VCD" .vcd)"
OUT="${OUT:-$POWER/out_${base}}"
ACT_JSON="$OUT/activity.json"
ACT_TCL="$OUT/activity.tcl"

if [[ ! -f "$VCD" ]]; then
  echo "ERROR: VCD not found: $VCD" >&2
  echo "Generate a gate-level VCD with: ./simulation/run_gls.sh fw --vcd" >&2
  echo "Or RTL: ./simulation/run_sim.sh fw --vcd" >&2
  exit 1
fi
if [[ ! -d "$RUN_DIR/final" ]]; then
  echo "ERROR: OpenLane run final/ missing: $RUN_DIR" >&2
  echo "Set RUN_DIR to a completed synthesis run." >&2
  exit 1
fi

NETLIST="$RUN_DIR/final/nl/sky130_vex2_soc.nl.v"

# DESIGN_PERIOD_NS: env > config.yaml CLOCK_PERIOD > 20
if [[ -z "${DESIGN_PERIOD_NS:-}" ]]; then
  if [[ -f "$CFG" ]]; then
    DESIGN_PERIOD_NS="$(python3 -c "
import re, sys
t=open(sys.argv[1]).read()
m=re.search(r'(?m)^CLOCK_PERIOD:\s*([0-9.]+)', t)
print(m.group(1) if m else '')
" "$CFG")"
  fi
  DESIGN_PERIOD_NS="${DESIGN_PERIOD_NS:-20}"
fi

# Stdcell liberty must match the hardened netlist (hd/hs/ms/…).
resolve_stdcell_lib() {
  if [[ -n "${STD_CELL_LIBRARY:-}" ]]; then
    echo "$STD_CELL_LIBRARY"
    return
  fi
  if [[ -f "$CFG" ]]; then
    local from_cfg
    from_cfg="$(python3 -c "
import re, sys
t=open(sys.argv[1]).read()
m=re.search(r'(?m)^STD_CELL_LIBRARY:\s*(\S+)', t)
print(m.group(1) if m else '')
" "$CFG")"
    if [[ -n "$from_cfg" ]]; then
      echo "$from_cfg"
      return
    fi
  fi
  if [[ -f "$NETLIST" ]]; then
    python3 -c "
import re, sys
t=open(sys.argv[1], errors='replace').read(2_000_000)
m=re.search(r'(sky130_fd_sc_(?:hd|hs|ms|ls|lp|hdll))__', t)
print(m.group(1) if m else 'sky130_fd_sc_hd')
" "$NETLIST"
    return
  fi
  echo "sky130_fd_sc_hd"
}

STD_CELL_LIBRARY="$(resolve_stdcell_lib)"
LIB_SC="$PDK_ROOT/sky130A/libs.ref/$STD_CELL_LIBRARY/lib/${STD_CELL_LIBRARY}__tt_025C_1v80.lib"
if [[ ! -f "$LIB_SC" ]]; then
  echo "ERROR: liberty not found: $LIB_SC" >&2
  exit 1
fi

if [[ "$SKIP_CLEAN" != "1" ]]; then
  echo "==> Cleaning previous power output: $OUT"
  rm -rf "$OUT"
fi
mkdir -p "$OUT"

echo "==> Power inputs"
echo "    VCD=$VCD"
echo "    RUN_DIR=$RUN_DIR"
echo "    STD_CELL_LIBRARY=$STD_CELL_LIBRARY"
echo "    DESIGN_PERIOD_NS=$DESIGN_PERIOD_NS"
echo "    LIB_SC=$LIB_SC"

echo "==> [1/3] Extracting activity from $VCD"
python3 "$POWER/vcd_to_activity.py" "$VCD" \
  --scope "$SCOPE" \
  --design-period-ns "$DESIGN_PERIOD_NS" \
  -o "$ACT_JSON" \
  --sta-tcl "$ACT_TCL"

export RUN_DIR POWER_OUT="$OUT" ACTIVITY_TCL="$ACT_TCL"
export LIB_SC
export LIB_SRAM="$ROOT/synthesis/sky130_vex2_soc/macros/sram22_2048x32m8w8_tt_025C_1v80.lib"

echo "==> [2/3] OpenSTA activity-based power (period=${DESIGN_PERIOD_NS} ns)"
echo "    (loading liberty/netlist/SPEF — may take a minute; no per-% bar here)"
cd "$ROOT"
nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config \
  "$OL2" -c \
  sta -no_splash -exit "$POWER/power_activity_sta.tcl"
echo "    OpenSTA done"

echo "==> [3/3] Summarizing energy"
python3 "$POWER/summarize_energy.py" \
  --activity-json "$ACT_JSON" \
  --power-rpt "$OUT/power_activity.rpt" \
  --clock-rpt "$OUT/power_clock_tree.rpt" \
  --design-period-ns "$DESIGN_PERIOD_NS" \
  -o "$OUT/power_energy.txt"

echo
echo "Reports:"
echo "  $OUT/power_energy.txt"
echo "  $OUT/power_activity.rpt"
echo "  $OUT/power_awake.rpt"
echo "  $OUT/power_sleep.rpt"
echo "  $OUT/power_clock_tree.rpt"
echo "  $OUT/activity.json"
echo
cat "$OUT/power_energy.txt"
