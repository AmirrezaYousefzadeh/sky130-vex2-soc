#!/usr/bin/env bash
# Install Determinate Nix with OpenLane binary cache (needs sudo via the installer).
# After this, clone OpenLane 2 under /media/hardware_design_tools/openlane2
set -euo pipefail

if command -v nix >/dev/null 2>&1; then
  echo "Nix already installed: $(command -v nix)"
  nix --version
  exit 0
fi

echo "Installing Nix (Determinate) with OpenLane cachix…"
echo "You will be prompted for your sudo password by the installer."
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install --no-confirm --extra-conf "
extra-substituters = https://openlane.cachix.org
extra-trusted-public-keys = openlane.cachix.org-1:qqdwh+QMNGmZAuyeQJTH9ErW57OWSvdtuwfBKdS254E=
"
echo ""
echo "Nix installed. Open a new shell (or source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh),"
echo "then run: ./setup/install_openlane.sh"
