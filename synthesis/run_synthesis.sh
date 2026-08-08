#!/usr/bin/env bash
# Synthesize / place-and-route sky130_vex2_soc with OpenLane 2, then print results.
#
# Usage:
#   ./synthesis/run_synthesis.sh
#   TO=OpenROAD.STAPostPNR ./synthesis/run_synthesis.sh   # fast: stop after timing
#   (default runs further; Magics streamout/IR-drop are off in config.json)
#
# Env:
#   RUN_TAG=name          run directory name (default sky130_vex2_soc)
#   CFG=path              OpenLane config (YAML/JSON)
#   FROM=Step.Id          resume from step
#   TO=Step.Id            stop after step (default OpenROAD.STAPostPNR)
#   OVERWRITE=0           keep existing run (needed with FROM)
#   PDK_ROOT / PDK / OPENLANE_ROOT
#
# Clock period (ns) lives in:
#   synthesis/sky130_vex2_soc/config.yaml  →  CLOCK_PERIOD
set -euo pipefail

export PATH="/nix/var/nix/profiles/default/bin:$PATH"
source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYNTH="$(cd "$(dirname "$0")" && pwd)"
export PDK_ROOT="${PDK_ROOT:-/media/pdk}"
export PDK="${PDK:-sky130A}"
OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"
DES="$SYNTH/sky130_vex2_soc"
CFG="${CFG:-$DES/config.yaml}"
RUN_TAG="${RUN_TAG:-sky130_vex2_soc}"
FROM="${FROM:-}"
TO="${TO:-OpenROAD.STAPostPNR}"
OVERWRITE="${OVERWRITE:-1}"
REPORT_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --report-only) REPORT_ONLY=1 ;;
    --full) TO="" ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

report() {
  python3 "$SYNTH/report_results.py" \
    --design-dir "$DES" \
    --run-tag "$RUN_TAG" \
    --config "$CFG"
}

if [[ "$REPORT_ONLY" == "1" ]]; then
  report
  exit 0
fi

echo "PDK_ROOT=$PDK_ROOT  PDK=$PDK"
echo "Config: $CFG"
echo "Run tag: $RUN_TAG"
[[ -n "$FROM" ]] && echo "Resume from: $FROM"
[[ -n "$TO" ]] && echo "Stop at: $TO"

EXTRA=()
if [[ -n "$FROM" ]]; then
  EXTRA+=(--from "$FROM")
  OVERWRITE=0
fi
if [[ -n "$TO" ]]; then
  EXTRA+=(--to "$TO")
fi
if [[ "$OVERWRITE" == "1" ]]; then
  EXTRA+=(--overwrite)
fi

cd "$DES"
set +e
nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config \
  "$OL2" -c \
  python3 -m openlane \
    --pdk-root "$PDK_ROOT" \
    --pdk "$PDK" \
    --manual-pdk \
    --run-tag "$RUN_TAG" \
    "${EXTRA[@]}" \
    "$CFG"
rc=$?
set -e

echo
echo "======== Synthesis results ========"
# Always try to report (STA metrics are enough even if signoff failed).
report || true
exit "$rc"