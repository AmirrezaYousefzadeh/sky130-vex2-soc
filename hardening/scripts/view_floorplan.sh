#!/usr/bin/env bash
# Open post-macro-placement design in OpenROAD GUI via read_db.
set -euo pipefail
export PATH="/nix/var/nix/profiles/default/bin:$PATH"
source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"
ODB="${1:-$ROOT/hardening/sky130_vex2_soc/runs/sky130_vex2_soc/12-odb-manualmacroplacement/sky130_vex2_soc.odb}"

if [[ ! -f "$ODB" ]]; then
  echo "Missing ODB: $ODB"
  exit 1
fi

TCL="$(mktemp /tmp/view_floorplan_XXXX.tcl)"
cat > "$TCL" <<EOF
read_db "$ODB"
puts "Loaded: $ODB"
EOF

echo "Opening ODB in OpenROAD GUI: $ODB"
cd "$OL2"
# shellcheck disable=SC2064
trap 'rm -f "$TCL"' EXIT
exec nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config -c \
  openroad -gui "$TCL"
