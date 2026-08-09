#!/usr/bin/env bash
# Run area/Fmax exploration experiments through OpenROAD.STAPostPNR.
#
# Usage:
#   ./scripts/run_explore.sh                         # default set
#   ./scripts/run_explore.sh area_1750x1000_p28 fmax_1800x1100_p18
#
# Env:
#   SKIP_CLEAN=1   keep previous explore_logs/ and explore_* run dirs
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
SKIP_CLEAN="${SKIP_CLEAN:-0}"

python3 "$ROOT/synthesis/scripts/explore_area_fmax.py" --write "$@"

DEFAULT=(area_1750x1000_p28 area_1680x950_p28 fmax_1800x1100_p18)
NAMES=("$@")
if [[ ${#NAMES[@]} -eq 0 ]]; then
  NAMES=("${DEFAULT[@]}")
fi

LOGDIR="$ROOT/synthesis/sky130_vex2_soc/explore_logs"
if [[ "$SKIP_CLEAN" != "1" ]]; then
  echo "==> Cleaning previous explore artifacts"
  rm -rf "$LOGDIR"
  for name in "${NAMES[@]}"; do
    rm -rf "$ROOT/synthesis/sky130_vex2_soc/runs/explore_${name}"
  done
fi
mkdir -p "$LOGDIR"
SUMMARY="$LOGDIR/summary.tsv"
echo -e "name\tdie_mm2\tperiod_ns\tstatus\tperiod_min_tt\tfmax_tt\tperiod_min_ss\tfmax_ss\twns_tt" >"$SUMMARY"

extract_metrics() {
  local tag="$1"
  local run="$ROOT/synthesis/sky130_vex2_soc/runs/$tag"
  local tt="$run"/*/50-openroad-stapostpnr/nom_tt_025C_1v80/clock.rpt
  local ss="$run"/*/50-openroad-stapostpnr/nom_ss_100C_1v60/clock.rpt
  # step dir may not be 50- if earlier steps skipped differently — glob
  tt=$(find "$run" -path '*/nom_tt_025C_1v80/clock.rpt' 2>/dev/null | head -1 || true)
  ss=$(find "$run" -path '*/nom_ss_100C_1v60/clock.rpt' 2>/dev/null | head -1 || true)
  local ptt="-" ftt="-" pss="-" fss="-" wns="-"
  if [[ -n "$tt" && -f "$tt" ]]; then
    ptt=$(rg -o 'period_min = ([0-9.]+)' -r '$1' "$tt" | head -1)
    ftt=$(rg -o 'fmax = ([0-9.]+)' -r '$1' "$tt" | head -1)
  fi
  if [[ -n "$ss" && -f "$ss" ]]; then
    pss=$(rg -o 'period_min = ([0-9.]+)' -r '$1' "$ss" | head -1)
    fss=$(rg -o 'fmax = ([0-9.]+)' -r '$1' "$ss" | head -1)
  fi
  local metrics
  metrics=$(find "$run" -name metrics.json | tail -1 || true)
  if [[ -n "$metrics" ]]; then
    wns=$(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(m.get('timing__setup__wns__corner:nom_tt_025C_1v80','-'))" "$metrics" 2>/dev/null || echo "-")
  fi
  echo -e "${ptt}\t${ftt}\t${pss}\t${fss}\t${wns}"
}

for name in "${NAMES[@]}"; do
  cfg="$ROOT/synthesis/sky130_vex2_soc/explore_${name}.json"
  tag="explore_${name}"
  log="$LOGDIR/${name}.log"
  die_mm2=$(python3 -c "import json; d=json.load(open('$cfg')); a=d['DIE_AREA']; print(round(a[2]*a[3]/1e6,3))")
  period=$(python3 -c "import json; print(json.load(open('$cfg'))['CLOCK_PERIOD'])")
  echo "=== $name  die=${die_mm2}mm2  period=${period}ns  tag=$tag ==="
  set +e
  CFG="$cfg" RUN_TAG="$tag" TO=OpenROAD.STAPostPNR OVERWRITE=1 \
    "$ROOT/synthesis/run_synthesis.sh" >"$log" 2>&1
  rc=$?
  set -e
  if [[ $rc -eq 0 ]]; then
    status="OK"
    metrics=$(extract_metrics "$tag")
  else
    status="FAIL"
    metrics=$'-\t-\t-\t-\t-'
    echo "FAILED rc=$rc — see $log"
    rg -n "ERROR|OpenLane will now quit|GRT-0232" "$log" | tail -15 || true
  fi
  echo -e "${name}\t${die_mm2}\t${period}\t${status}\t${metrics}" | tee -a "$SUMMARY"
done

echo
echo "Summary: $SUMMARY"
column -t -s $'\t' "$SUMMARY" || cat "$SUMMARY"
