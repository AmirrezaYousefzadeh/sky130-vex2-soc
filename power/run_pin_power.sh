#!/usr/bin/env bash
# Activity-aware (per-pin) OpenSTA power of sky130_vex2_soc from a gate-level VCD, over a time window.
#   ./power/run_pin_power.sh <vcd> <out_dir> [--begin T --end T]      (T in VCD time units; default: the whole waveform)
# Steps: power/tools/vcd_toggles streams the VCD and counts the transitions and high time of every variable of the u_soc scope
# (OpenSTA's read_power_activities rules); toggles_to_activity.py turns them into set_power_activity commands for every pin /
# net / top-level port; power_pin_sta.tcl annotates the post-PnR netlist + SPEF, stops the clock propagation at the clock
# gates (so gated clock trees count what the waveform shows) and reports the power. The SRAM macros use the vdd-only liberty
# (sram22_..._pwr.lib) so that their internal power is not counted twice.
# Env: RUN_DIR (OpenLane run), PERIOD_NS (default: CLOCK_PERIOD of config.yaml), SCOPE (default: <tb module>/u_soc, sniffed),
#      LIB_SRAM, PDK_ROOT, OPENLANE_ROOT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; POWER="$ROOT/power"
VCD="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; OUT="$2"; shift 2
BEGIN=""; END=""
while [[ $# -gt 0 ]]; do case "$1" in --begin) BEGIN="$2"; shift 2;; --end) END="$2"; shift 2;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
DES="$ROOT/synthesis/sky130_vex2_soc"
export PDK_ROOT="${PDK_ROOT:-/media/pdk}"; OL2="${OPENLANE_ROOT:-/media/hardware_design_tools/openlane2}"
export RUN_DIR="${RUN_DIR:-$DES/runs/sky130_vex2_soc}" TOP=sky130_vex2_soc MACRO_INST="u_imem u_dmem"
if [[ -z "${PERIOD_NS:-}" ]]; then
  PERIOD_NS="$(python3 -c "import re,sys;t=open(sys.argv[1]).read();m=re.search(r'(?m)^CLOCK_PERIOD:\s*([0-9.]+)',t);print(m.group(1) if m else 20)" "$DES/config.yaml")"
fi
export PERIOD_NS
STD_CELL_LIBRARY="${STD_CELL_LIBRARY:-$(python3 -c "import re,sys;t=open(sys.argv[1]).read();m=re.search(r'(?m)^STD_CELL_LIBRARY:\s*(\S+)',t);print(m.group(1) if m else 'sky130_fd_sc_ms')" "$DES/config.yaml")}"
export LIB_SC="${LIB_SC:-$PDK_ROOT/sky130A/libs.ref/$STD_CELL_LIBRARY/lib/${STD_CELL_LIBRARY}__tt_025C_1v80.lib}"
export LIB_SRAM="${LIB_SRAM:-$DES/macros/sram22_2048x32m8w8_tt_025C_1v80_pwr.lib}"
if [[ -z "${SCOPE:-}" ]]; then   # testbench module name from the VCD header
  TBMOD="$(grep -a -m1 '^\$scope module' "$VCD" | awk '{print $3}')"; SCOPE="$TBMOD/u_soc"
fi
export VCD_SCOPE="$SCOPE" OUT
[[ -x "$POWER/tools/vcd_toggles" ]] || cc -O2 -o "$POWER/tools/vcd_toggles" "$POWER/tools/vcd_toggles.c"
rm -rf "$OUT"; mkdir -p "$OUT"
WOPT=(); [[ -n "$BEGIN" ]] && WOPT+=(--begin "$BEGIN"); [[ -n "$END" ]] && WOPT+=(--end "$END")
echo "==> toggles: $VCD ${WOPT[*]:-(whole waveform)}"
"$POWER/tools/vcd_toggles" -o "$OUT/toggles.tsv" "${WOPT[@]}" "$VCD" 2> "$OUT/toggles.log" || { tail -5 "$OUT/toggles.log"; exit 1; }
PERIOD_S=$(python3 -c "print($PERIOD_NS * 1e-9)")
python3 "$POWER/tools/toggles_to_activity.py" "$OUT/toggles.tsv" --scope "$VCD_SCOPE" --period-s "$PERIOD_S" -o "$OUT/activity.tcl" --summary "$OUT/activity_summary.json" | tee "$OUT/activity.log"
export ACT_TCL="$OUT/activity.tcl"
echo "==> OpenSTA per-pin power (period $PERIOD_NS ns, lib $STD_CELL_LIBRARY)"
export PATH="/nix/var/nix/profiles/default/bin:$PATH"; source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh 2>/dev/null || true
nix --extra-experimental-features "nix-command flakes" develop --accept-flake-config "$OL2" -c sta -no_splash -exit "$POWER/power_pin_sta.tcl" > "$OUT/sta.log" 2>&1 || { tail -20 "$OUT/sta.log"; exit 1; }
grep -E "CLK_STOP|WROTE" "$OUT/sta.log"
python3 - "$OUT" "$PERIOD_NS" <<'EOF'
import json, re, sys
from pathlib import Path
out = Path(sys.argv[1]); rpt = (out / "power_pin.rpt").read_text()
groups = {}
for name in ("Sequential", "Combinational", "Clock", "Macro", "Pad", "Total"):
    m = re.search(rf"^{name}\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", rpt, re.M)
    if m: groups[name.lower()] = {"internal_W": float(m.group(1)), "switching_W": float(m.group(2)), "leakage_W": float(m.group(3)), "total_W": float(m.group(4))}
hdr = {}
for line in (out / "toggles.tsv").open():
    if not line.startswith("#"): break
    k, v = line[1:].rstrip("\n").split("\t"); hdr[k] = float(v)
dur = (hdr["time_max"] - hdr["time_min"]) * hdr["timescale_s"]
res = {"groups": groups, "total_W": groups["total"]["total_W"], "duration_s": dur, "period_ns": float(sys.argv[2]),
       "energy_J": groups["total"]["total_W"] * dur, "cycles": dur / (float(sys.argv[2]) * 1e-9)}
json.dump(res, open(out / "summary.json", "w"), indent=1)
print(f"total {1e3*res['total_W']:.4f} mW over {1e6*dur:.1f} us ({res['cycles']:.0f} cycles) = {1e6*res['energy_J']:.4f} uJ; "
      + ", ".join(f"{k} {1e3*v['total_W']:.3f}" for k, v in groups.items() if k != "total") + " mW")
EOF
