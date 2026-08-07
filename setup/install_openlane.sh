#!/usr/bin/env bash
# Clone OpenLane 2 under /media/hardware_design_tools and verify via nix-shell.
set -euo pipefail

export PATH="/nix/var/nix/profiles/default/bin:$PATH"
HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
PDK_ROOT="${PDK_ROOT:-/media/pdk}"
OL_DIR="$HARDWARE_TOOLS_ROOT/openlane2"

if [[ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]]; then
  # shellcheck disable=SC1091
  source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
fi

if ! command -v nix >/dev/null 2>&1; then
  echo "ERROR: nix not found. Run: bash setup/install_nix.sh"
  exit 1
fi

if [[ ! -d "$OL_DIR/.git" ]]; then
  echo "Cloning OpenLane 2 into $OL_DIR …"
  git clone --depth 1 https://github.com/efabless/openlane2.git "$OL_DIR"
else
  echo "OpenLane already present at $OL_DIR"
fi

echo "Entering nix-shell and checking OpenLane (first time may download ~1–5 GB)…"
cd "$OL_DIR"
# Prefer flake develop/run — avoids nix profile install + package check segfaults
nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config -c \
  python3 -m openlane --version 2>&1 | tee /tmp/openlane_version.log

echo ""
echo "OpenLane root: $OL_DIR"
echo "PDK_ROOT=$PDK_ROOT"
cat > "$HARDWARE_TOOLS_ROOT/openlane_run.sh" <<EOF
#!/usr/bin/env bash
# Run OpenLane 2 with shared PDK
set -euo pipefail
export PATH="/nix/var/nix/profiles/default/bin:\$PATH"
export PDK_ROOT="\${PDK_ROOT:-/media/pdk}"
source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh 2>/dev/null || true
cd "$OL_DIR"
exec nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config -c \\
  python3 -m openlane --pdk-root "\$PDK_ROOT" --manual-pdk "\$@"
EOF
chmod +x "$HARDWARE_TOOLS_ROOT/openlane_run.sh"

echo "Helper: $HARDWARE_TOOLS_ROOT/openlane_run.sh <config.json>"
echo "Done."
