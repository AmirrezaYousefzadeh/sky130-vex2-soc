# Third-party sources

Not vendored in git. Fetch with:

```bash
./setup/fetch_third_party.sh
```

| Directory | Upstream | Used for |
|-----------|----------|----------|
| `VexRiscv/` | SpinalHDL/VexRiscv | Regenerate `rtl/cpu/VexRiscv2.v` |
| `sram22_sky130_macros/` | ucb-bar/sram22_sky130_macros | Behavioral model + LEF/GDS/LIB |

After cloning SRAM22, prepare OpenLane macro views:

```bash
./setup/prepare_macros.sh
```
