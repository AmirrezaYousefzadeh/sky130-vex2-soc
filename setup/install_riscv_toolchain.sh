#!/usr/bin/env bash
# Install xPack RISC-V bare-metal GCC under repo tools/ for firmware builds.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/tools"
VERSION="${RISCV_XPACK_VERSION:-14.2.0-3}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ARCH_TAG=linux-x64 ;;
  aarch64|arm64) ARCH_TAG=linux-arm64 ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

DIR="xpack-riscv-none-elf-gcc-${VERSION}"
URL="https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v${VERSION}/${DIR}-${ARCH_TAG}.tar.gz"

mkdir -p "$TOOLS"
if [[ -x "$TOOLS/$DIR/bin/riscv-none-elf-gcc" ]]; then
  echo "Toolchain already present: $TOOLS/$DIR"
  ln -sfn "$DIR" "$TOOLS/riscv-none-elf-gcc"
  exit 0
fi

TGZ="$TOOLS/riscv-gcc.tar.gz"
echo "Downloading $URL"
curl -L --fail -o "$TGZ" "$URL"
tar -xzf "$TGZ" -C "$TOOLS"
ln -sfn "$DIR" "$TOOLS/riscv-none-elf-gcc"
echo "Done: $TOOLS/riscv-none-elf-gcc/bin/riscv-none-elf-gcc"
"$TOOLS/riscv-none-elf-gcc/bin/riscv-none-elf-gcc" --version | head -1
