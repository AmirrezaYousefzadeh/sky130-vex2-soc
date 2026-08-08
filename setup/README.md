# Setup (PDK + tools)

Scripts to prepare the shared SkyWater PDK and EDA tooling used by simulation, synthesis, and power.

Default install roots (override with env vars):

| Path | Env | Purpose |
|------|-----|---------|
| `/media/pdk` | `PDK_ROOT` | sky130A via volare |
| `/media/hardware_design_tools` | `HARDWARE_TOOLS_ROOT` | OpenLane 2, OSS CAD Suite, volare venv |

After install, from the repo root:

```bash
source env.sh
```

## Suggested order

```bash
# 1) One-time directory ownership (needs your sudo password)
sudo bash ./sudo_setup_media_pdk.sh
sudo bash ./sudo_setup_media_tools.sh

# 2) Nix (OpenLane uses flakes / nix develop)
./install_nix.sh
# open a new shell, or: source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh

# 3) sky130 PDK (~2+ GB)
./install_pdk.sh
# optional pin: OPEN_PDKS_REV=<hash> ./install_pdk.sh

# 4) OpenLane 2
./install_openlane.sh

# 5) Optional local tools (simulation / firmware)
./install_oss_cad_suite.sh    # iverilog, yosys, gtkwave, …
./install_riscv_toolchain.sh  # riscv-none-elf-gcc → ../tools/
./fetch_third_party.sh        # VexRiscv + SRAM22 macro sources
./prepare_macros.sh           # LEF/GDS/LIB into synthesis/.../macros
```

## Scripts

| Script | What it does |
|--------|----------------|
| `sudo_setup_media_pdk.sh` | `mkdir` + permissions on `/media/pdk` |
| `sudo_setup_media_tools.sh` | same for `/media/hardware_design_tools` |
| `install_nix.sh` | Determinate Nix + OpenLane cachix |
| `install_pdk.sh` | volare venv + enable sky130 |
| `install_openlane.sh` | clone OpenLane 2 + write; writes `openlane_run.sh` |
| `install_oss_cad_suite.sh` | download OSS CAD Suite into tools root |
| `install_riscv_toolchain.sh` | xPack RISC-V GCC under `../tools/` |
| `fetch_third_party.sh` | clone VexRiscv + sram22_sky130_macros |
| `prepare_macros.sh` | copy/patch SRAM22 LEF/GDS/LIB into synthesis macros |

## Parameters / knobs

| Variable | Used by | Meaning |
|----------|---------|---------|
| `PDK_ROOT` | PDK / OpenLane / power | PDK install root |
| `PDK` | OpenLane | usually `sky130A` |
| `HARDWARE_TOOLS_ROOT` | all installs | tools root |
| `OPENLANE_ROOT` | harden / power | OpenLane 2 checkout |
| `OPEN_PDKS_REV` | `install_pdk.sh` | pin open_pdks git rev for volare |

Clock period and floorplan knobs for the chip itself are **not** here — they live in `../synthesis/sky130_vex2_soc/config.yaml` (`CLOCK_PERIOD`, etc.).
