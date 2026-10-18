#!/usr/bin/env bash
# Complete measurement of the event-driven N-MNIST workload:
#   1. full event stream on the RTL model          -> decision latency, awake cycles per event (docs/results/nmnist_sim.txt)
#   2. short stream (first K events) gate-level + SDF + VCD -> OpenSTA awake / sleep power (power/out_<vcd>/power_energy.txt)
#   3. energy per event / to the decision / per sample (docs/results/nmnist_energy.txt)
#   4. optional: full stream at gate level without SDF (zero delay) to confirm PASS on the netlist
#
# Usage: ./power/measure_nmnist.sh [K=100]
# Env:   RUN_DIR (OpenLane run with final/nl, final/sdf, final/spef), OPT (-O3 default), FULL_GLS=1 for step 4,
#        DUMP_LEVEL (default 1), SKIP_RTL=1 / SKIP_GLS=1 to reuse previous results.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
K="${1:-100}"
export OPT="${OPT:--O3}"
export DUMP_LEVEL="${DUMP_LEVEL:-1}"
RES="$ROOT/docs/results"
SHORT="$ROOT/firmware/nmnist/short$K"
mkdir -p "$RES"

if [[ "${SKIP_RTL:-0}" != "1" ]]; then
  echo "==> [1/4] RTL simulation of the full event stream"
  "$ROOT/simulation/run_sim.sh" nmnist 2>&1 | grep -v "^VCD info" | tee "$RES/nmnist_sim.txt" | grep -E "TB:|PASS|FAIL"
fi

if [[ "${SKIP_GLS:-0}" != "1" ]]; then
  echo "==> [2/4] trimmed sample (first $K events) for the gate-level power run"
  python3 "$ROOT/firmware/nmnist/trim_sample.py" --src "$ROOT/firmware/nmnist" --dst "$SHORT" --events "$K"
  echo "==> [2/4] gate-level simulation with SDF and VCD (short stream)"
  NMNIST_DIR="$SHORT" VCD_NAME="waveform_gls_nmnist.vcd" "$ROOT/simulation/run_gls.sh" nmnist --vcd 2>&1 | tee "$RES/nmnist_gls_short.txt" | grep -E "TB:|PASS|FAIL|SDF:|VCD|Gate-level"
  echo "==> [3/4] per-pin OpenSTA power: whole short waveform and the longest idle window"
  V="$ROOT/simulation/waveform_gls_nmnist.vcd"
  python3 "$ROOT/power/vcd_windows.py" "$V" -o "$ROOT/power/out_pin_nmnist_windows.json"
  "$ROOT/power/run_pin_power.sh" "$V" "$ROOT/power/out_pin_nmnist_full" 2>&1 | tail -2
  IB=$(python3 -c "import json;print(json.load(open('$ROOT/power/out_pin_nmnist_windows.json'))['idle'][0])")
  IE=$(python3 -c "import json;print(json.load(open('$ROOT/power/out_pin_nmnist_windows.json'))['idle'][1])")
  "$ROOT/power/run_pin_power.sh" "$V" "$ROOT/power/out_pin_nmnist_idle" --begin "$IB" --end "$IE" 2>&1 | tail -2
  if [[ "${LEGACY_POWER:-0}" == "1" ]]; then   # the global-activity flow of the MNIST snapshot, for comparison
    SCOPE=tb_fw_nmnist.u_soc "$ROOT/power/run_avg_power.sh" "$V" 2>&1 | tail -5
    cp -f "$ROOT/power/out_waveform_gls_nmnist/power_energy.txt" "$RES/nmnist_power_energy.txt"
    python3 "$ROOT/power/nmnist_energy.py" --power "$RES/nmnist_power_energy.txt" --sim "$RES/nmnist_sim.txt" --out "$RES/nmnist_energy.txt"
  fi
fi

echo "==> [3/4] energy / latency summary (per-pin)"
python3 "$ROOT/power/pin_energy.py" --kind nmnist --full "$ROOT/power/out_pin_nmnist_full" --idle "$ROOT/power/out_pin_nmnist_idle" \
  --windows "$ROOT/power/out_pin_nmnist_windows.json" --short_sim "$RES/nmnist_gls_short.txt" --sim "$RES/nmnist_sim.txt" --out "$RES/nmnist_pin_energy.txt"

if [[ "${FULL_GLS:-0}" == "1" ]]; then
  echo "==> [4/4] full stream at gate level (zero delay, no VCD)"
  "$ROOT/simulation/run_gls.sh" nmnist --no-sdf 2>&1 | tee "$RES/nmnist_gls_full.txt" | grep -E "TB:|PASS|FAIL"
fi
echo "done: $RES/nmnist_sim.txt $RES/nmnist_pin_energy.txt"
