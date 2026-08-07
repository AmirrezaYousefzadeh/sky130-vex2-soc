#!/usr/bin/env bash
# Create shared tools root on /media (run yourself with sudo).
set -euo pipefail

mkdir -p /media/hardware_design_tools
chown yousefzadeha:users /media/hardware_design_tools
chmod 2775 /media/hardware_design_tools

echo "OK: /media/hardware_design_tools ready"
ls -lad /media/hardware_design_tools
