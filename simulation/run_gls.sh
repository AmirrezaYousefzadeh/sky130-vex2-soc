#!/usr/bin/env bash
# Gate-level simulation of post-PnR sky130_vex2_soc netlist → VCD for power.
#
# Uses:
#   - OpenLane final/nl/*.nl.v  (no power pins; flat stdcell netlist)
#   - sky130_fd_sc_hd FUNCTIONAL cell models + UDP primitives
#   - Behavioral SRAM22 model (same backdoor $readmemh as RTL sim)
#
# Usage:
#   ./simulation/run_gls.sh              # smoke (default)
#   ./simulation/run_gls.sh smoke
#   ./simulation/run_gls.sh fw           # MNIST MLP firmware (no VCD by default)
#   ./simulation/run_gls.sh fw --vcd     # firmware + gate-level VCD
#
# Env:
#   RUN_DIR=path           OpenLane run with final/nl (default: .../sky130_vex2_soc_v2)
#   DUMP_VCD=1             same as --vcd for fw
#   VCD_NAME=name.vcd      output under simulation/
#   TIMEOUT_CYCLES=N       fw halt timeout (default 5000000)
#   DUMP_LEVEL=1           $dumpvars depth (default 1 = SoC nets, not cell internals)
#   PDK_ROOT / HARDWARE_TOOLS_ROOT
#
# Note: zero-delay FUNCTIONAL GLS (no SDF). Good for toggle activity / power;
#       timing-annotated GLS is a separate, heavier step.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIM="$(cd "$(dirname "$0")" && pwd)"
HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
PDK_ROOT="${PDK_ROOT:-/media/pdk}"
RUN_DIR="${RUN_DIR:-$ROOT/synthesis/sky130_vex2_soc/runs/sky130_vex2_soc_v2}"
DUMP_LEVEL="${DUMP_LEVEL:-1}"

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
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

NETLIST="$RUN_DIR/final/nl/sky130_vex2_soc.nl.v"
CELL_V="$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"
PRIM_V="$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v"
SRAM_V="$ROOT/rtl/sram/sram22_2048x32m8w8.v"

if [[ ! -f "$NETLIST" ]]; then
  echo "ERROR: gate netlist not found: $NETLIST" >&2
  echo "Set RUN_DIR to a completed OpenLane run (needs final/nl/)." >&2
  exit 1
fi
for f in "$CELL_V" "$PRIM_V" "$SRAM_V"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing $f" >&2
    exit 1
  fi
done

OUT="$SIM/build_gls"
mkdir -p "$OUT"
cd "$OUT"

# Match RTL $readmemb(zeros) so x0/reads are not X in the synthesized RF.
python3 "$SIM/gen_gls_regfile_init.py" -o "$OUT/gls_regfile_init.vh" --scope u_soc

# FUNCTIONAL = zero-delay behavioral cells; no USE_POWER_PINS (nl.v has none).
GLS_DEFS=(
  -DFUNCTIONAL
  -DUNIT_DELAY='#1'
  -DGLS_RF_INIT
)
GLS_SRCS=(
  "$PRIM_V"
  "$CELL_V"
  "$SRAM_V"
  "$NETLIST"
)

case "$MODE" in
  smoke)
    VCD_NAME="${VCD_NAME:-sky130_vex2_soc_gls.vcd}"
    VCD_PATH="$SIM/$VCD_NAME"
    echo "==> GLS smoke compile (netlist: $NETLIST)"
    iverilog -g2012 -o soc_gls.vvp \
      "${GLS_DEFS[@]}" \
      -DDUMP_PATH="\"$VCD_PATH\"" \
      -DDUMP_LEVEL="$DUMP_LEVEL" \
      -DDUMP_MODULE=tb_sky130_vex2_soc.u_soc \
      "${GLS_SRCS[@]}" \
      "$SIM/tb_sky130_vex2_soc.v"
    echo "==> Running GLS smoke..."
    vvp soc_gls.vvp
    ln -sfn "$VCD_NAME" "$SIM/latest_gls.vcd"
    echo "Gate-level waveform: $VCD_PATH"
    ;;
  fw|mnist|firmware)
    make -C "$ROOT/firmware" all
    cp -f "$ROOT/firmware/build/imem.hex" "$ROOT/firmware/build/dmem.hex" .
    DUMP_VCD="${DUMP_VCD:-0}"
    DUMP_FLAGS=()
    if [[ "$DUMP_VCD" == "1" ]]; then
      VCD_NAME="${VCD_NAME:-mnist_mlp_gls.vcd}"
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
    iverilog -g2012 -o fw_mnist_gls.vvp \
      "${GLS_DEFS[@]}" \
      -DIMEM_HEX="\"imem.hex\"" \
      -DDMEM_HEX="\"dmem.hex\"" \
      -DTIMEOUT_CYCLES="$TIMEOUT" \
      "${DUMP_FLAGS[@]}" \
      "${GLS_SRCS[@]}" \
      "$SIM/tb_fw_mnist.v"
    echo "==> Running GLS MNIST MLP firmware..."
    vvp fw_mnist_gls.vvp
    if [[ "$DUMP_VCD" == "1" ]]; then
      ln -sfn "$VCD_NAME" "$SIM/latest_gls.vcd"
      echo "Gate-level waveform: $VCD_PATH"
      echo "Power: ./power/run_power.sh $VCD_PATH"
    fi
    ;;
  -h|--help|help)
    sed -n '2,28p' "$0"
    exit 0
    ;;
  *)
    echo "Unknown mode: $MODE (use smoke|fw)" >&2
    exit 2
    ;;
esac
