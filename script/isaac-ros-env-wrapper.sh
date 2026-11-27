#!/bin/bash
#
# isaac-ros-env-wrapper.sh — hard-bake ROS env from build-time choice
#
# Reads /etc/isaac/ros-distro (written at build time from the [[build.args]]
# entry with key = "ROS_DISTRO" in setup.toml) and exports ROS_DISTRO and
# LD_LIBRARY_PATH unconditionally before exec'ing the wrapped command. Runtime
# `-e ROS_DISTRO=...` flags are ignored — distro is a build-time choice
# in this repo; rebuild the image (`just docker build`) to switch.
#
# Wired in via headless / gui ENTRYPOINT:
#   ENTRYPOINT ["/usr/local/bin/isaac-ros-env-wrapper.sh", "/isaac-sim/runheadless.sh"]
# CMD args land in $@ verbatim.

set -euo pipefail

if [[ ! -f /etc/isaac/ros-distro ]]; then
  echo "[isaac-ros-env-wrapper] ERROR: /etc/isaac/ros-distro missing" >&2
  echo "[isaac-ros-env-wrapper] Image must be built with ARG ROS_DISTRO." >&2
  exit 1
fi

ROS_DISTRO="$(< /etc/isaac/ros-distro)"
export ROS_DISTRO
export LD_LIBRARY_PATH="/isaac-sim/exts/isaacsim.ros2.core/${ROS_DISTRO}/lib"

EXTRA_ARGS=()
if [[ -n "${PUBLIC_IP:-}" ]]; then
  EXTRA_ARGS+=("--/app/livestream/publicEndpointAddress=${PUBLIC_IP}")
fi

exec "$@" "${EXTRA_ARGS[@]}"
