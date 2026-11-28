# Model Assets

Robot models (URDF and USD) live in the private
[ycpss91255-lab/sim_asset](https://github.com/ycpss91255-lab/sim_asset) repository.
For relative scene model paths, mount the repository and set `MODEL_PATH`
to its in-container mount point. Separate multiple roots with colons in search order.

The `sw/` and `object/` subdirectories remain here as placeholders for
SolidWorks source files and object assets respectively.

## Moved models

Paths are relative to the sim_asset repository root. See “分層與規則” and
“Repository 結構” in the [sim_asset README](https://github.com/ycpss91255-lab/sim_asset/blob/main/README.md).

| Model | URDF | USD |
|-------|------|-----|
| omwr | `model/robot/custom/omwr/` | `usd/robot/custom/omwr/` |
| openbase | `model/robot/guiritter/openbase/` | `usd/robot/guiritter/openbase/` |
