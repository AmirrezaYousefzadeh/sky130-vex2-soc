# Shared sky130 PDK + hardware design tools paths.
# Usage: source env.sh

export PDK_ROOT="${PDK_ROOT:-/media/pdk}"
export PDK="${PDK:-sky130A}"
export HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
export OPENLANE_ROOT="${OPENLANE_ROOT:-$HARDWARE_TOOLS_ROOT/openlane2}"

# Nix
export PATH="/nix/var/nix/profiles/default/bin:$PATH"
if [[ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]]; then
  # shellcheck disable=SC1091
  source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi

# Volare venv
if [[ -f "$HARDWARE_TOOLS_ROOT/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$HARDWARE_TOOLS_ROOT/venv/bin/activate"
fi

# OSS CAD Suite (iverilog, yosys, gtkwave, …)
if [[ -d "$HARDWARE_TOOLS_ROOT/oss-cad-suite/bin" ]]; then
  export PATH="$HARDWARE_TOOLS_ROOT/oss-cad-suite/bin:$PATH"
fi

echo "PDK_ROOT=$PDK_ROOT  PDK=$PDK  HARDWARE_TOOLS_ROOT=$HARDWARE_TOOLS_ROOT"
echo "OpenLane: $HARDWARE_TOOLS_ROOT/openlane_run.sh <config.json>"
