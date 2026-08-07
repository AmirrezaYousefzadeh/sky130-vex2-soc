#!/usr/bin/env bash
# Create shared PDK root on /media (run this yourself with sudo).
set -euo pipefail

# Shared so group "users" can read/use the PDK; you own it for installs/updates.
mkdir -p /media/pdk
chown yousefzadeha:users /media/pdk
chmod 2775 /media/pdk   # setgid: new files inherit group "users"

echo "OK: /media/pdk ready"
ls -lad /media/pdk
