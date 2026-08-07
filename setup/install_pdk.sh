#!/usr/bin/env bash
# Install sky130 PDK via volare into /media/pdk (shared PDK_ROOT).
set -euo pipefail

PDK_ROOT="${PDK_ROOT:-/media/pdk}"
HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
export PDK_ROOT

if [[ ! -d "$PDK_ROOT" ]]; then
  echo "ERROR: $PDK_ROOT does not exist."
  echo "Run: sudo bash $(cd "$(dirname "$0")" && pwd)/sudo_setup_media_pdk.sh"
  exit 1
fi
if [[ ! -w "$PDK_ROOT" ]]; then
  echo "ERROR: $PDK_ROOT is not writable by $(whoami)."
  echo "Run: sudo bash $(cd "$(dirname "$0")" && pwd)/sudo_setup_media_pdk.sh"
  exit 1
fi

# Prefer shared tools dir for the volare venv; fall back to PDK_ROOT.
if [[ -d "$HARDWARE_TOOLS_ROOT" && -w "$HARDWARE_TOOLS_ROOT" ]]; then
  VENV="$HARDWARE_TOOLS_ROOT/venv"
else
  echo "NOTE: $HARDWARE_TOOLS_ROOT not ready; using $PDK_ROOT/venv for volare."
  echo "      Later run: sudo bash setup/sudo_setup_media_tools.sh"
  VENV="$PDK_ROOT/venv"
fi

echo "PDK_ROOT=$PDK_ROOT"
echo "VENV=$VENV"

python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip wheel
pip install -U volare

OPEN_PDKS_REV="${OPEN_PDKS_REV:-}"

if [[ -z "$OPEN_PDKS_REV" ]]; then
  echo "Listing remote sky130 builds..."
  mapfile -t REVS < <(volare ls-remote --pdk sky130 2>/dev/null | awk '{print $1}' | head -5)
  if [[ ${#REVS[@]} -eq 0 ]]; then
    echo "Could not list remote builds; using fallback open_pdks rev."
    OPEN_PDKS_REV="7519dfb04400f224f140749cda44ee7de6f5e095"
  else
    OPEN_PDKS_REV="${REVS[0]}"
  fi
fi

echo "Enabling sky130 @ $OPEN_PDKS_REV (download can be several GB)..."
volare enable --pdk-root "$PDK_ROOT" --pdk sky130 "$OPEN_PDKS_REV"

echo ""
echo "Done. Disk usage:"
du -sh "$PDK_ROOT" 2>/dev/null || true
du -sh "$PDK_ROOT"/* 2>/dev/null | head -20 || true
ls -la "$PDK_ROOT" | head -30
echo ""
echo "Add to your shell (or: source env.sh):"
echo "  export PDK_ROOT=$PDK_ROOT"
echo "  export PDK=sky130A"
echo "  export HARDWARE_TOOLS_ROOT=$HARDWARE_TOOLS_ROOT"
echo "  source $VENV/bin/activate   # for volare"
