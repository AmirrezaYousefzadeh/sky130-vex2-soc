#!/usr/bin/env bash
# View floorplan DEF in KLayout (often better over remote/X11 than OpenROAD GUI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARDWARE_TOOLS_ROOT="${HARDWARE_TOOLS_ROOT:-/media/hardware_design_tools}"
export PATH="$HARDWARE_TOOLS_ROOT/oss-cad-suite/bin:$PATH"

DEF="${1:-$ROOT/hardening/sky130_vex2_soc/runs/sky130_vex2_soc/12-odb-manualmacroplacement/sky130_vex2_soc.def}"

if ! command -v klayout >/dev/null 2>&1; then
  echo "klayout not found (expected under $HARDWARE_TOOLS_ROOT/oss-cad-suite/bin)"
  exit 1
fi
if [[ ! -f "$DEF" ]]; then
  echo "Missing DEF: $DEF"
  exit 1
fi

echo "Opening DEF in KLayout: $DEF"
echo "Tip: File → Reader Options → LEF/DEF — add tech LEF + sram22 LEF if layers look empty."
exec klayout -e "$DEF"
