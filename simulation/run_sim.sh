#!/usr/bin/env bash
# Run RTL simulation of sky130_vex2_soc and write VCD waveforms into this folder.
#
# Usage:
#   ./simulation/run_sim.sh              # smoke test (default)
#   ./simulation/run_sim.sh smoke
#   ./simulation/run_sim.sh fw           # MNIST MLP firmware
#   ./simulation/run_sim.sh fw --vcd     # firmware + VCD dump
#
# Env / parameters:
#   DUMP_VCD=1           same as --vcd for fw (default: on for smoke, off for fw)
#   TIMEOUT_CYCLES=N     fw halt timeout (default 5000000)
#   VCD_NAME=name.vcd    output filename under simulation/
#   HARDWARE_TOOLS_ROOT  OSS CAD Suite location (default /media/hardware_design_tools)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIM="$(cd "$(dirname "$0")" && pwd)"
HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"

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

OUT="$SIM/build"
mkdir -p "$OUT"
cd "$OUT"
cp -f "$ROOT/rtl/cpu/VexRiscv2.v_toplevel_RegFilePlugin_regFile.bin" .

RTL=(
  "$ROOT/rtl/cpu/VexRiscv2.v"
  "$ROOT/rtl/sram/sram22_2048x32m8w8.v"
  "$ROOT/rtl/soc/ibus_sram22_bridge.v"
  "$ROOT/rtl/soc/dbus_sram22_bridge.v"
  "$ROOT/rtl/soc/sky130_vex2_soc.v"
)

case "$MODE" in
  smoke)
    VCD_NAME="${VCD_NAME:-sky130_vex2_soc.vcd}"
    VCD_PATH="$SIM/$VCD_NAME"
    iverilog -g2012 -o soc.vvp \
      -DDUMP_PATH="\"$VCD_PATH\"" \
      "${RTL[@]}" \
      "$SIM/tb_sky130_vex2_soc.v"
    echo "Running smoke simulation..."
    vvp soc.vvp
    ln -sfn "$VCD_NAME" "$SIM/latest.vcd"
    echo "Waveform: $VCD_PATH"
    ;;
  fw|mnist|firmware)
    make -C "$ROOT/fw" all
    cp -f "$ROOT/fw/build/imem.hex" "$ROOT/fw/build/dmem.hex" .
    # Default: dump VCD for fw when DUMP_VCD unset → off; --vcd or DUMP_VCD=1 enables
    DUMP_VCD="${DUMP_VCD:-0}"
    DUMP_FLAGS=()
    if [[ "$DUMP_VCD" == "1" ]]; then
      VCD_NAME="${VCD_NAME:-mnist_mlp.vcd}"
      VCD_PATH="$SIM/$VCD_NAME"
      DUMP_FLAGS+=(-DDUMP_PATH="\"$VCD_PATH\"")
      echo "VCD dump enabled: $VCD_PATH"
    fi
    TIMEOUT="${TIMEOUT_CYCLES:-5000000}"
    iverilog -g2012 -o fw_mnist.vvp \
      -DIMEM_HEX="\"imem.hex\"" \
      -DDMEM_HEX="\"dmem.hex\"" \
      -DTIMEOUT_CYCLES="$TIMEOUT" \
      "${DUMP_FLAGS[@]}" \
      "${RTL[@]}" \
      "$SIM/tb_fw_mnist.v"
    echo "Running MNIST MLP firmware simulation..."
    vvp fw_mnist.vvp
    if [[ "$DUMP_VCD" == "1" ]]; then
      ln -sfn "$VCD_NAME" "$SIM/latest.vcd"
      echo "Waveform: $VCD_PATH"
    fi
    ;;
  -h|--help|help)
    sed -n '2,16p' "$0"
    exit 0
    ;;
  *)
    echo "Unknown mode: $MODE (use smoke|fw)" >&2
    exit 2
    ;;
esac
