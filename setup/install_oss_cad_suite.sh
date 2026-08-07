#!/usr/bin/env bash
# Download OSS CAD Suite into HARDWARE_TOOLS_ROOT (iverilog, yosys, gtkwave, …).
set -euo pipefail

HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${OSS_CAD_DIR:-$HARDWARE_TOOLS_ROOT/oss-cad-suite}"
VERSION="${OSS_CAD_VERSION:-2024-12-05}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ARCH_TAG=linux-x64 ;;
  aarch64|arm64) ARCH_TAG=linux-arm64 ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="${OSS_CAD_URL:-https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${VERSION}/oss-cad-suite-${ARCH_TAG}-${VERSION//-/}.tgz}"
# YosysHQ tag format often YYYY-MM-DD with filename YYYYMMDD — allow override
if [[ -z "${OSS_CAD_URL:-}" ]]; then
  DAY="${VERSION//-/}"
  URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${VERSION}/oss-cad-suite-${ARCH_TAG}-${DAY}.tgz"
fi

mkdir -p "$HARDWARE_TOOLS_ROOT"
TGZ="$HARDWARE_TOOLS_ROOT/oss-cad-suite.tgz"

if [[ -x "$DEST/bin/iverilog" ]]; then
  echo "OSS CAD Suite already present: $DEST"
  "$DEST/bin/iverilog" -V | head -1 || true
  exit 0
fi

echo "Downloading $URL"
curl -L --fail -o "$TGZ" "$URL"
echo "Extracting to $DEST …"
rm -rf "$DEST"
mkdir -p "$DEST"
tar -xzf "$TGZ" -C "$HARDWARE_TOOLS_ROOT"
# tarball usually unpacks as oss-cad-suite/
if [[ ! -d "$DEST" ]]; then
  echo "ERROR: expected $DEST after extract" >&2
  exit 1
fi

# Convenience symlink in repo tools/
mkdir -p "$ROOT/tools"
ln -sfn "$DEST" "$ROOT/tools/oss-cad-suite"
echo "Done. iverilog: $DEST/bin/iverilog"
echo "Add to PATH via: source $ROOT/env.sh"
