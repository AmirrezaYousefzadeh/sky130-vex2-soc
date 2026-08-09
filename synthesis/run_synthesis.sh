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
#   SKIP_CLEAN=1          do not delete prior run dir / floorplan / ad-hoc logs
#   SKIP_FLOORPLAN=1      skip floorplan PNG at end
#   PDK_ROOT / PDK / OPENLANE_ROOT
#
# Clock period and stdcell library live in:
#   synthesis/sky130_vex2_soc/config.yaml  →  CLOCK_PERIOD, STD_CELL_LIBRARY
# After a successful (or partial) run, also writes:
#   synthesis/sky130_vex2_soc/synthesis_results.txt
#   synthesis/sky130_vex2_soc/floorplan_real.png
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
SKIP_CLEAN="${SKIP_CLEAN:-0}"
SKIP_FLOORPLAN="${SKIP_FLOORPLAN:-0}"
REPORT_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --report-only) REPORT_ONLY=1 ;;
    --full) TO="" ;;
    -h|--help)
      sed -n '2,24p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

report() {
  python3 "$SYNTH/report_results.py" \
    --design-dir "$DES" \
    --run-tag "$RUN_TAG" \
    --config "$CFG" \
    -o "$DES/runs/$RUN_TAG/synthesis_results.txt" \
    -o "$DES/synthesis_results.txt"
}

floorplan_png() {
  if [[ "$SKIP_FLOORPLAN" == "1" ]]; then
    return 0
  fi
  echo
  echo "======== Floorplan PNG ========"
  # Cap runtime: a bad/huge DEF used to hang forever after PnR finished.
  if command -v timeout >/dev/null 2>&1; then
    RUN_TAG="$RUN_TAG" SKIP_CLEAN=1 \
      timeout 90 "$SYNTH/scripts/save_floorplan_png.sh" || {
        echo "WARNING: floorplan PNG failed or timed out (DEF missing / plot error)" >&2
        return 0
      }
  else
    RUN_TAG="$RUN_TAG" SKIP_CLEAN=1 \
      "$SYNTH/scripts/save_floorplan_png.sh" || {
        echo "WARNING: floorplan PNG failed (DEF missing or plot error)" >&2
        return 0
      }
  fi
}

if [[ "$REPORT_ONLY" == "1" ]]; then
  floorplan_png
  echo
  echo "======== Synthesis results ========"
  report || true
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

# Wipe prior outputs for this tag so old runs / logs / floorplans do not pile up.
# Skip when resuming (FROM set / OVERWRITE=0) or SKIP_CLEAN=1.
if [[ "$SKIP_CLEAN" != "1" && "$OVERWRITE" == "1" ]]; then
  echo "==> Cleaning previous synthesis artifacts for tag '$RUN_TAG'"
  rm -rf "$DES/runs/$RUN_TAG"
  rm -f "$DES"/floorplan_*.png
  rm -f "$DES"/harden*.log
  rm -f "$DES"/synthesis_results.txt
  rm -rf "$DES/logs"
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

# Floorplan before the timing report so the report is the last thing on screen.
floorplan_png

echo
echo "======== Synthesis results ========"
# Always try to report (STA metrics are enough even if signoff failed).
report || true
exit "$rc"
