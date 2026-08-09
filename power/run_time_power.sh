#!/usr/bin/env bash
# Time-windowed activity-based power (Joules-style timeline).
#
# Slices the VCD into N equal time windows (default 1000), runs OpenSTA
# average power per window, and writes a power VCD (µW stairsteps) viewable
# in GTKWave / Surfer.
#
# Hierarchy depth=1 on this flat post-PnR netlist:
#   top, u_imem, u_dmem, logic (= top - macros)
# Each block: total_uW + static_uW (static = OpenSTA Leakage).
# Sleep: core ICG GATE case-analyzed per window from VCD sram_clk_en duty.
#
# Usage:
#   ./run_time_power.sh ../simulation/waveform_gls.vcd
#   ./run_time_power.sh ../simulation/waveform_gls.vcd --windows 100
#   WINDOWS=200 DEPTH=1 ./run_time_power.sh
#
# Env / flags:
#   VCD / first arg     input waveform
#   --windows N         equal time slots (default 1000)
#   --depth N           hierarchy depth (only 1 implemented for now)
#   RUN_DIR DESIGN_PERIOD_NS STD_CELL_LIBRARY OUT SCOPE PDK_ROOT OPENLANE_ROOT
#   SKIP_CLEAN=1
#
# Writes under OUT (default power/out_<vcd>_time/):
#   power_vs_time.vcd   hierarchy power traces (µW)
#   power_vs_time.csv   same data (free side-car)
#   power_time_summary.txt
#   windows.json        per-window activity
#   sta_time.log        full OpenSTA transcript
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POWER="$(cd "$(dirname "$0")" && pwd)"
DES="$ROOT/synthesis/sky130_vex2_soc"
CFG="${CFG:-$DES/config.yaml}"
export ROOT
export PDK_ROOT="${PDK_ROOT:-/media/pdk}"
OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"
SKIP_CLEAN="${SKIP_CLEAN:-0}"
WINDOWS="${WINDOWS:-1000}"
DEPTH="${DEPTH:-1}"

ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --windows)
      WINDOWS="$2"
      shift 2
      ;;
    --windows=*)
      WINDOWS="${1#*=}"
      shift
      ;;
    --depth)
      DEPTH="$2"
      shift 2
      ;;
    --depth=*)
      DEPTH="${1#*=}"
      shift
      ;;
    -h|--help)
      sed -n '2,40p' "$0"
      exit 0
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

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

# Resolve relative paths: try cwd first, then repo-rooted alternatives.
resolve_vcd() {
  local p="$1"
  if [[ -f "$p" ]]; then
    echo "$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
    return
  fi
  # Common mistake: ../simulation/... from repo root instead of from power/
  if [[ "$p" == ../simulation/* && -f "$ROOT/simulation/${p#../simulation/}" ]]; then
    echo "$ROOT/simulation/${p#../simulation/}"
    return
  fi
  if [[ "$p" == simulation/* && -f "$ROOT/$p" ]]; then
    echo "$ROOT/$p"
    return
  fi
  if [[ "$p" == ./simulation/* && -f "$ROOT/${p#./}" ]]; then
    echo "$ROOT/${p#./}"
    return
  fi
  echo "$p"
}
VCD="$(resolve_vcd "$VCD")"

RUN_DIR="${RUN_DIR:-$DES/runs/sky130_vex2_soc}"
SCOPE="${SCOPE:-tb_fw_mnist.u_soc}"
base="$(basename "$VCD" .vcd)"
OUT="${OUT:-$POWER/out_${base}_time}"
WIN_JSON="$OUT/windows.json"
ACT_TCL="$OUT/activity_windows.tcl"

if [[ "$DEPTH" != "1" ]]; then
  echo "NOTE: --depth=$DEPTH requested; only depth=1 (top/u_imem/u_dmem/logic) is implemented." >&2
fi

if [[ ! -f "$VCD" ]]; then
  echo "ERROR: VCD not found: $VCD" >&2
  echo "Tried from cwd and $ROOT/simulation/." >&2
  echo "From repo root: ./power/run_time_power.sh ./simulation/waveform_gls.vcd" >&2
  echo "From power/:     ./run_time_power.sh ../simulation/waveform_gls.vcd" >&2
  echo "Generate with:   ./simulation/run_gls.sh fw --vcd" >&2
  exit 1
fi
if [[ ! -d "$RUN_DIR/final" ]]; then
  echo "ERROR: OpenLane run final/ missing: $RUN_DIR" >&2
  exit 1
fi

NETLIST="$RUN_DIR/final/nl/sky130_vex2_soc.nl.v"

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
  echo "==> Cleaning previous time-power output: $OUT"
  rm -rf "$OUT"
fi
mkdir -p "$OUT"

echo "==> Time-power inputs"
echo "    VCD=$VCD"
echo "    RUN_DIR=$RUN_DIR"
echo "    WINDOWS=$WINDOWS"
echo "    DEPTH=$DEPTH"
echo "    STD_CELL_LIBRARY=$STD_CELL_LIBRARY"
echo "    DESIGN_PERIOD_NS=$DESIGN_PERIOD_NS"
echo "    OUT=$OUT"

echo "==> Extracting per-window activity"
python3 "$POWER/vcd_to_windows.py" "$VCD" \
  --scope "$SCOPE" \
  --windows "$WINDOWS" \
  --design-period-ns "$DESIGN_PERIOD_NS" \
  -o "$WIN_JSON" \
  --sta-tcl "$ACT_TCL"

export RUN_DIR POWER_OUT="$OUT" ACTIVITY_TCL="$ACT_TCL"
export LIB_SC
export LIB_SRAM="$ROOT/synthesis/sky130_vex2_soc/macros/sram22_2048x32m8w8_tt_025C_1v80.lib"

STA_LOG="$OUT/sta_time.log"
echo "==> OpenSTA windowed power (one design load, $WINDOWS windows)"
cd "$ROOT"
# stdbuf helps progress markers appear live through nix/sta pipes.
set +e
stdbuf -oL -eL nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config \
  "$OL2" -c \
  stdbuf -oL -eL sta -no_splash -exit "$POWER/power_time_sta.tcl" \
  2> "$OUT/sta_time.err" | tee "$STA_LOG" | \
  python3 "$POWER/emit_time_power.py" \
    --windows-json "$WIN_JSON" \
    --vcd-out "$OUT/power_vs_time.vcd" \
    --csv-out "$OUT/power_vs_time.csv" \
    --summary-out "$OUT/power_time_summary.txt"
statuses=("${PIPESTATUS[@]}")
set -e

STA_PIPE_STATUS="${statuses[0]:-1}"
EMIT_STATUS="${statuses[2]:-${statuses[1]:-1}}"

if [[ "$STA_PIPE_STATUS" -ne 0 ]]; then
  echo "ERROR: OpenSTA failed (exit $STA_PIPE_STATUS). See $OUT/sta_time.err" >&2
  exit "$STA_PIPE_STATUS"
fi
if [[ "$EMIT_STATUS" -ne 0 ]]; then
  echo "ERROR: emit_time_power failed (exit $EMIT_STATUS)" >&2
  exit "$EMIT_STATUS"
fi

echo
echo "Reports:"
echo "  $OUT/power_vs_time.vcd"
echo "  $OUT/power_vs_time.csv"
echo "  $OUT/power_time_summary.txt"
echo "  $OUT/windows.json"
