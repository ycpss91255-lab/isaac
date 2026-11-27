#!/usr/bin/env bash
# gpu_job_lib.sh -- steps shared by the self-hosted GPU job scripts
# (gpu_integration_job.sh, stream_smoke_job.sh). Sourced, not executed.
#
# Those jobs run through the org reusable workflow
# ycpss91255-lab/.github/.github/workflows/gpu-self-hosted.yml, which
# reclaims the workspace, checks out, and then runs ONE repo script. The
# steps below used to be inline workflow steps; they keep their old names
# as log groups.

# Log group helpers (collapsible sections in the Actions log).
gpu_job_group() { echo "::group::$*"; }
gpu_job_endgroup() { echo "::endgroup::"; }

# base detect_ws_path mis-detects the self-CI _work/<repo>/<repo> layout:
# none of its strategies (docker_* sibling, *_ws ancestor) match, so the
# parent-dir fallback returns _work/<repo> -- one level too high, leaving the
# repo at ~/work/<repo>/ inside the container. The workspace [[volumes]] entry
# in setup.toml uses source = "${WS_PATH}", so apply re-detects WS_PATH and ignores a
# job-env override. Pin it in the derived .env.generated cache AFTER apply
# (the --env-file the wrappers pass to compose) so the compose mounts the
# repo root at ~/work. base follow-up: base#586.
gpu_job_apply_and_pin_ws_path() {
  gpu_job_group "Generate .env + compose.yaml (pin WS_PATH)"
  ./script/setup.sh apply
  sed -i "s|^WS_PATH=.*|WS_PATH=${GITHUB_WORKSPACE:?}|" .env.generated
  gpu_job_endgroup
}

# CI keeps the shared image name `isaac` (the GPU tests resolve
# <hub>/isaac:test) and each suite pins its own per-run PROJECT_NAME, so only
# the build opts out of the pre-build shared-identity guard
# (script/checkout_identity.sh, base#1551). The opt-out is scoped to this one
# command, as the old step-level env was.
gpu_job_build() {
  local stage="$1"
  gpu_job_group "Build ${stage} stage (cached if unchanged)"
  ISAAC_ALLOW_SHARED_IDENTITY=1 ./script/build.sh -t "${stage}"
  gpu_job_endgroup
}

# Pre-create writable bind mounts for the non-root container user. The shader
# and compute caches persist outside the workspace, keyed by Isaac Sim version
# by default. Checkout cleans the workspace links without touching the cache
# contents. The remaining state lives in the workspace and starts cold.
gpu_job_cache_dirs() {
  local LC_ALL=C
  local cache_root="${ISAAC_CI_CACHE_ROOT:-${HOME}/isaac-ci-cache}"
  local key="${ISAAC_CI_CACHE_KEY:-}"
  local dockerfile="${GITHUB_WORKSPACE:?}/Dockerfile" image

  gpu_job_group "Pre-create Isaac Sim cache mount dirs (writable)"
  if [[ -z "${key}" && -f "${dockerfile}" ]]; then
    image="$(awk '$1 == "ARG" && sub(/^BASE_IMAGE=/, "", $2) {
      gsub(/["\047]/, "", $2)
      print $2
      exit
    }' "${dockerfile}")"
    image="${image%%@*}"
    if [[ "${image##*/}" == *:* ]]; then
      key="${image##*:}"
    fi
  fi
  key="${key//[^a-zA-Z0-9._-]/_}"
  case "${key}" in
    ''|.|..) key=default ;;
  esac
  local cache_dir="${cache_root}/${key}"
  mkdir -p "${cache_dir}/kit-cache" "${cache_dir}/computecache"
  chmod a+rwX "${cache_dir}/kit-cache" "${cache_dir}/computecache"

  mkdir -p \
    isaac-sim/kit/data isaac-sim/kit/logs \
    isaac-sim/ov/cache isaac-sim/ov/data isaac-sim/ov/logs \
    isaac-sim/pip isaac-sim/nvidia/glcache isaac-sim/documents
  rm -rf isaac-sim/kit/cache isaac-sim/nvidia/computecache
  ln -sr -- "${cache_dir}/kit-cache" isaac-sim/kit/cache
  ln -sr -- "${cache_dir}/computecache" isaac-sim/nvidia/computecache

  # Rootless Docker: the container's non-root user maps to a subuid on the
  # host, so files owned by the runner are not writable inside the container.
  # chmod a+rwX makes the workspace (repo root, cache dirs, test-report dir)
  # accessible for any uid.  The runner user keeps ownership, so host-side
  # steps (setup.sh apply, git) still work.  Harmless on a rootful daemon.
  # See ycpss91255-lab/.github#38, isaac#314.
  chmod -R a+rwX "${GITHUB_WORKSPACE:-.}"
  gpu_job_endgroup
}
