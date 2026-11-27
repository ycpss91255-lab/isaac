# Drop the Isaac Lab dependency from isaac

Status: Accepted (2026-11-27)

## Context

ADR-0018 adopted Isaac Lab for scene spawning, application startup, and URDF
import. The goal for `isaac` is to keep differences from NVIDIA's official
`isaac-sim` image minimal. In #473, the image comparison showed that the
`isaac-lab` image uses a different UID, home directory (`HOME`), and Python
virtual environment from `isaac-sim`. Switching the base would change the
runtime environment for everyone using Isaac Sim.

## Decision

`isaac` provides Isaac Sim only, with no Isaac Lab dependency. Its base image
stays at `nvcr.io/nvidia/isaac-sim:6.2.0.1`.

This supersedes ADR-0018's choice of the Isaac Lab `sim_utils` spawn backend
and `AppLauncher` for startup. It also moves responsibility for URDF import
(ADR-0020) to `asset_converter`. The input to `isaac` is the converted USD.

## Consequences

Users who need Isaac Lab use the `isaac_lab` repository. It references
`isaac` as a submodule and swaps only the base image.

This ADR records the decision for #476 in the #475 series. Follow-ups
#477 through #480 implement the removal.
