#!/usr/bin/env bash
# Gate-level simulation of post-PnR sky130_vex2_soc netlist → VCD for power.
#
# Default: SDF-annotated timing GLS (sanitized cell IOPATH delays) so
# combinational glitches appear in the waveform. Use --no-sdf for fast
# zero-delay FUNCTIONAL GLS.
#
# Uses:
#   - OpenLane final/nl/*.nl.v  (no power pins; flat stdcell netlist)
#   - Matching sky130_fd_sc_* timing/FUNCTIONAL models + UDP primitives
#   - OpenLane final/sdf/.../*.sdf  (default: nom_tt_025C_1v80)
#   - Behavioral SRAM22 model (same backdoor $readmemh as RTL sim)
#
# Usage:
#   ./simulation/run_gls.sh              # smoke + SDF (default)
#   ./simulation/run_gls.sh smoke
#   ./simulation/run_gls.sh fw           # MNIST MLP firmware (no VCD by default)
#   ./simulation/run_gls.sh fw --vcd     # firmware + gate-level VCD
#   ./simulation/run_gls.sh fw --vcd --no-sdf   # zero-delay fallback
#
# Env:
#   RUN_DIR=path           OpenLane run with final/nl (+ final/sdf for SDF mode)
#   STD_CELL_LIBRARY=name  Override (else from config.yaml, else sniffed from netlist)
#   SDF=path               SDF file (default: RUN_DIR/final/sdf/nom_tt_025C_1v80/*.sdf)
#   SDF_CORNER=name        Corner dir under final/sdf/ (default nom_tt_025C_1v80)
#   NO_SDF=1               same as --no-sdf
#   SDF_VERBOSE=1          log every SDF annotate step (very noisy / slow)
#   DUMP_VCD=1             same as --vcd for fw
#   VCD_NAME=name.vcd      output under simulation/
#   TIMEOUT_CYCLES=N       fw halt timeout (default 5000000)
#   DUMP_LEVEL=1           $dumpvars depth (default 1 = SoC nets, not cell internals)
#   SKIP_CLEAN=1           keep previous build_gls/ + GLS VCDs (default: clean first)
#   PDK_ROOT / HARDWARE_TOOLS_ROOT
#
# Clock: edit CLK_PERIOD_NS in simulation/tb_*.v (must be ≥ hardened period for SDF).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIM="$(cd "$(dirname "$0")" && pwd)"
DES="$ROOT/synthesis/sky130_vex2_soc"
CFG="${CFG:-$DES/config.yaml}"
HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
PDK_ROOT="${PDK_ROOT:-/media/pdk}"
# Match synthesis/run_synthesis.sh default RUN_TAG.
RUN_DIR="${RUN_DIR:-$DES/runs/sky130_vex2_soc}"
DUMP_LEVEL="${DUMP_LEVEL:-1}"
SKIP_CLEAN="${SKIP_CLEAN:-0}"
NO_SDF="${NO_SDF:-0}"
SDF_CORNER="${SDF_CORNER:-nom_tt_025C_1v80}"

if [[ -x "$HARDWARE_TOOLS_ROOT/oss-cad-suite/bin/iverilog" ]]; then
  export PATH="$HARDWARE_TOOLS_ROOT/oss-cad-suite/bin:$PATH"
elif [[ -x "$ROOT/tools/oss-cad-suite/bin/iverilog" ]]; then
  export PATH="$ROOT/tools/oss-cad-suite/bin:$PATH"
fi
export PATH="$ROOT/tools/riscv-none-elf-gcc/bin:$PATH"

MODE="${1:-smoke}"
shift || true
DUMP_VCD="${DUMP_VCD:-}"
for arg in "$@"; do
  case "$arg" in
    --vcd) DUMP_VCD=1 ;;
    --no-vcd) DUMP_VCD=0 ;;
    --no-sdf) NO_SDF=1 ;;
    --sdf) NO_SDF=0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

NETLIST="$RUN_DIR/final/nl/sky130_vex2_soc.nl.v"
SRAM_V="$ROOT/rtl/sram/sram22_2048x32m8w8.v"

if [[ ! -f "$NETLIST" ]]; then
  echo "ERROR: gate netlist not found: $NETLIST" >&2
  echo "Set RUN_DIR to a completed OpenLane run (needs final/nl/)." >&2
  exit 1
fi

# Resolve stdcell library: env > config.yaml > sniff netlist.
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
  # Fallback: first sky130_fd_sc_*__ token in the netlist.
  python3 -c "
import re, sys
t=open(sys.argv[1], errors='replace').read(2_000_000)
m=re.search(r'(sky130_fd_sc_(?:hd|hs|ms|ls|lp|hdll))__', t)
print(m.group(1) if m else 'sky130_fd_sc_hd')
" "$NETLIST"
}

STD_CELL_LIBRARY="$(resolve_stdcell_lib)"
CELL_V="$PDK_ROOT/sky130A/libs.ref/$STD_CELL_LIBRARY/verilog/${STD_CELL_LIBRARY}.v"
PRIM_V="$PDK_ROOT/sky130A/libs.ref/$STD_CELL_LIBRARY/verilog/primitives.v"

for f in "$CELL_V" "$PRIM_V" "$SRAM_V"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing $f" >&2
    echo "STD_CELL_LIBRARY=$STD_CELL_LIBRARY  PDK_ROOT=$PDK_ROOT" >&2
    exit 1
  fi
done

# Sanity: netlist family should match chosen library.
if ! grep -q "${STD_CELL_LIBRARY}__" "$NETLIST"; then
  echo "WARNING: netlist does not mention ${STD_CELL_LIBRARY}__ — wrong RUN_DIR or library?" >&2
  echo "  RUN_DIR=$RUN_DIR" >&2
  echo "  STD_CELL_LIBRARY=$STD_CELL_LIBRARY" >&2
fi

# Resolve SDF (unless zero-delay mode).
SDF_FILE=""
if [[ "$NO_SDF" != "1" ]]; then
  if [[ -n "${SDF:-}" ]]; then
    SDF_FILE="$SDF"
  else
    SDF_DIR="$RUN_DIR/final/sdf/$SDF_CORNER"
    if [[ -d "$SDF_DIR" ]]; then
      SDF_FILE="$(find "$SDF_DIR" -maxdepth 1 -name '*.sdf' | head -1 || true)"
    fi
  fi
  if [[ -z "$SDF_FILE" || ! -f "$SDF_FILE" ]]; then
    echo "ERROR: SDF not found (corner=$SDF_CORNER)." >&2
    echo "Expected: $RUN_DIR/final/sdf/$SDF_CORNER/*.sdf" >&2
    echo "Or set SDF=/path/to/file.sdf, or pass --no-sdf for zero-delay GLS." >&2
    exit 1
  fi
fi

OUT="$SIM/build_gls"
# Default output name (overridable via VCD_NAME) — resolve before clean.
VCD_NAME="${VCD_NAME:-waveform_gls.vcd}"
if [[ "$SKIP_CLEAN" != "1" ]]; then
  echo "==> Cleaning previous GLS artifacts"
  # Primary build tree + any leftover experimental build_gls_* dirs
  rm -rf "$OUT"
  rm -rf "$SIM"/build_gls_*
  # Waveforms / symlink from prior GLS (avoid stale smoke VCD after fw, etc.)
  rm -f "$SIM/waveform_gls.vcd" "$SIM/latest_gls.vcd" "$SIM/$VCD_NAME"
  # Logs / hex copies accidentally left under simulation/
  rm -f "$SIM"/build_gls*.log "$SIM"/*_gls*.log
  rm -f "$SIM/imem.hex" "$SIM/dmem.hex"
fi
mkdir -p "$OUT"
cd "$OUT"

# Icarus-friendly SDF (see sdf_sanitize_for_icarus.py: drop INTERCONNECT /
# TIMINGCHECK / bit-select IOPATH; unwrap COND; fix min::max headers).
if [[ "$NO_SDF" != "1" ]]; then
  SDF_ICARUS="$OUT/sky130_vex2_soc.icarus.sdf"
  echo "==> Sanitizing SDF for Icarus"
  python3 "$SIM/sdf_sanitize_for_icarus.py" "$SDF_FILE" -o "$SDF_ICARUS"
  SDF_FILE="$SDF_ICARUS"
fi

# Match RTL $readmemb(zeros) so x0/reads are not X in the synthesized RF.
python3 "$SIM/gen_gls_regfile_init.py" -o "$OUT/gls_regfile_init.vh" --scope u_soc

GLS_DEFS=(-DGLS_RF_INIT)
IVERILOG_FLAGS=(-g2012)
# Source order: primitives → (optional timing stubs) → cells → SRAM → netlist → TB
GLS_SRCS=(
  "$PRIM_V"
)

echo "==> GLS inputs"
echo "    RUN_DIR=$RUN_DIR"
echo "    STD_CELL_LIBRARY=$STD_CELL_LIBRARY"
echo "    netlist=$NETLIST"

if [[ "$NO_SDF" == "1" ]]; then
  # Zero-delay behavioral cells; no USE_POWER_PINS (nl.v has none).
  GLS_DEFS+=(-DFUNCTIONAL -DUNIT_DELAY='#1')
  echo "==> GLS mode: zero-delay FUNCTIONAL (no SDF)"
else
  # Timing models + specify/INTERCONNECT so SDF delays (and glitches) apply.
  # UNIT_DELAY kept as a harmless fallback for any functional-only paths.
  # Clock period: edit CLK_PERIOD_NS in tb_*.v (must be long enough for SDF).
  GLS_DEFS+=(
    -DUNIT_DELAY='#1'
    -DSDF_ANNOTATE="\"$SDF_FILE\""
  )
  IVERILOG_FLAGS+=(-gspecify -ginterconnect -Ttyp)
  # hd timing lib has a broken lpflow_bleeder specify; ms/hs typically do not.
  if [[ "$STD_CELL_LIBRARY" == "sky130_fd_sc_hd" ]]; then
    GLS_SRCS+=("$SIM/sky130_timing_icarus_fixes.v")
  fi
  echo "==> GLS mode: SDF timing ($SDF_CORNER)"
  echo "    SDF: $SDF_FILE"
  echo "    Clock: edit CLK_PERIOD_NS in simulation/tb_*.v"
  echo "    Note: SDF annotate on this SoC can take a long time (Icarus + large SDF)."
fi

GLS_SRCS+=(
  "$CELL_V"
  "$SRAM_V"
  "$NETLIST"
)

compile_and_run() {
  local vvp="$1"
  shift
  echo "==> Compiling (warnings → $OUT/iverilog_warn.log) ..."
  # Timing-check "not supported" spam from the PDK; keep a log, show errors only.
  if ! iverilog "${IVERILOG_FLAGS[@]}" -o "$vvp" \
      "${GLS_DEFS[@]}" \
      "$@" \
      "${GLS_SRCS[@]}" \
      2>"$OUT/iverilog_warn.log"; then
    echo "ERROR: iverilog failed. Last lines of $OUT/iverilog_warn.log:" >&2
    tail -n 40 "$OUT/iverilog_warn.log" >&2
    exit 1
  fi
  local nwarn
  nwarn="$(grep -c 'warning:' "$OUT/iverilog_warn.log" 2>/dev/null || echo 0)"
  echo "    iverilog ok ($nwarn warnings logged)"
  echo "==> Running $vvp ..."
  if [[ "$NO_SDF" == "1" ]]; then
    vvp "$vvp"
  else
    echo "    (SDF annotation in progress — may be slow; log: $OUT/sdf_annotate.log)"
    if [[ "${SDF_VERBOSE:-0}" == "1" ]]; then
      vvp "$vvp" -sdf-verbose 2>"$OUT/sdf_annotate.log"
    else
      vvp "$vvp" 2>"$OUT/sdf_annotate.log"
    fi
    if grep -qE 'SDF ERROR|VPI error' "$OUT/sdf_annotate.log" 2>/dev/null; then
      local nerr
      nerr="$(grep -cE 'SDF ERROR|VPI error' "$OUT/sdf_annotate.log" || true)"
      echo "    SDF: finished with $nerr error/VPI lines (see $OUT/sdf_annotate.log)"
    else
      echo "    SDF: annotated (log: $OUT/sdf_annotate.log)"
    fi
  fi
}

case "$MODE" in
  smoke)
    VCD_PATH="$SIM/$VCD_NAME"
    echo "==> GLS smoke compile (netlist: $NETLIST)"
    compile_and_run soc_gls.vvp \
      -DDUMP_PATH="\"$VCD_PATH\"" \
      -DDUMP_LEVEL="$DUMP_LEVEL" \
      -DDUMP_MODULE=tb_sky130_vex2_soc.u_soc \
      "$SIM/tb_sky130_vex2_soc.v"
    python3 "$SIM/vcd_rescale_ns.py" "$VCD_PATH"
    ln -sfn "$VCD_NAME" "$SIM/latest_gls.vcd"
    echo "Gate-level waveform: $VCD_PATH"
    ;;
  fw|mnist|firmware)
    make -C "$ROOT/firmware" all
    cp -f "$ROOT/firmware/build/imem.hex" "$ROOT/firmware/build/dmem.hex" .
    DUMP_VCD="${DUMP_VCD:-0}"
    DUMP_FLAGS=()
    if [[ "$DUMP_VCD" == "1" ]]; then
      VCD_PATH="$SIM/$VCD_NAME"
      DUMP_FLAGS+=(
        -DDUMP_PATH="\"$VCD_PATH\""
        -DDUMP_LEVEL="$DUMP_LEVEL"
        -DDUMP_MODULE=tb_fw_mnist.u_soc
      )
      echo "Gate-level VCD dump enabled: $VCD_PATH (dumpvars level=$DUMP_LEVEL)"
    fi
    TIMEOUT="${TIMEOUT_CYCLES:-5000000}"
    echo "==> GLS firmware compile (netlist: $NETLIST)"
    compile_and_run fw_mnist_gls.vvp \
      -DIMEM_HEX="\"imem.hex\"" \
      -DDMEM_HEX="\"dmem.hex\"" \
      -DTIMEOUT_CYCLES="$TIMEOUT" \
      "${DUMP_FLAGS[@]}" \
      "$SIM/tb_fw_mnist.v"
    if [[ "$DUMP_VCD" == "1" ]]; then
      python3 "$SIM/vcd_rescale_ns.py" "$VCD_PATH"
      ln -sfn "$VCD_NAME" "$SIM/latest_gls.vcd"
      echo "Gate-level waveform: $VCD_PATH"
      echo "Power: ./power/run_power.sh $VCD_PATH"
    fi
    ;;
  -h|--help|help)
    sed -n '2,45p' "$0"
    exit 0
    ;;
  *)
    echo "Unknown mode: $MODE (use smoke|fw)" >&2
    exit 2
    ;;
esac
