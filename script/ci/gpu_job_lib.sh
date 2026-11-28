#!/usr/bin/env bash
# gpu_job_lib.sh -- steps shared by the self-hosted GPU job scripts
# Sourced by the integration, stream and headless job entry points.
# GPU jobs added by PR #541 (issue #437) must use gpu_job_cache_dirs too.
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

gpu_job_cache_key() {
  local LC_ALL=C key="${ISAAC_CI_CACHE_KEY:-}" image driver
  local dockerfile="${GITHUB_WORKSPACE:?}/Dockerfile"
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
  driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null)" || driver=
  driver="${driver%%$'\n'*}"
  driver="${driver:-nodriver}"
  printf '%s-%s\n' "${key}" "${driver//[^a-zA-Z0-9._-]/_}"
}

gpu_job_cold_cache() {
  [[ "${GITHUB_REF_TYPE:-}" == tag || "${GITHUB_REF:-}" == refs/tags/* ||
    "${ISAAC_CI_COLD_CACHE:-}" == 1 ]] && return 0
  [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch && -f "${GITHUB_EVENT_PATH:-}" ]] ||
    return 1
  if command -v jq >/dev/null; then
    jq -e '(.inputs.final_acceptance | tostring) == "true"' "${GITHUB_EVENT_PATH}" >/dev/null
  else
    python3 -c 'import json, sys
value = json.load(sys.stdin).get("inputs", {}).get("final_acceptance")
sys.exit(0 if value in (True, "true") else 1)' < "${GITHUB_EVENT_PATH}"
  fi
}

# A provisioned seed (or a partial copy of it) may have read-only directories.
gpu_job_remove_cache_tree() {
  local dir="$1"
  if ! rm -rf -- "${dir}" 2>/dev/null; then
    find "${dir}" -type d -uid "${UID}" -exec chmod u+rwx -- {} +
    rm -rf -- "${dir}"
  fi
}

# The caller holds seed.lock exclusively. Keep the previous seed recoverable
# if a rename fails or a runner stops between the two renames.
gpu_job_promote_cache() {
  local seed="${gpu_cache_key_dir}/seed" old="${gpu_cache_key_dir}/seed.old"
  if [[ -d "${seed}" ]]; then
    gpu_job_remove_cache_tree "${old}" || return 1
    mv -T -- "${seed}" "${old}" || return 1
  fi
  if ! mv -T -- "${gpu_cache_run}" "${seed}"; then
    if [[ -d "${old}" ]]; then
      mv -T -- "${old}" "${seed}"
    fi
    return 1
  fi
  gpu_job_remove_cache_tree "${old}"
}

# The root lock serializes key registration with retention. A shared lock on
# the key directory pins it until the job finishes, even across driver changes.
gpu_job_prune_cache() {
  local root="${gpu_cache_key_dir%/*}" entry dir kept=false
  while IFS= read -r -d '' entry; do
    dir="${root}/${entry#* }"
    [[ "${dir}" != "${gpu_cache_key_dir}" ]] || continue
    if [[ "${kept}" == false ]]; then
      kept=true
    elif flock -n "${dir}" true; then
      # The root lock prevents a new job from acquiring this idle key.
      gpu_job_remove_cache_tree "${dir}"
    fi
  done < <(find "${root}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\0' | sort -zrn)
}

gpu_job_finish_cache() {
  local rc="$1"
  trap 'rc=130' INT
  trap 'rc=143' TERM
  if [[ "${rc}" == 0 && "${gpu_cache_cold}" == false ]]; then
    {
      flock -x 9
      if (( rc == 0 )); then
        # Finish the rename pair once publication has started.
        trap '' INT TERM
        gpu_job_promote_cache || rc=$?
      fi
    } 9>>"${gpu_cache_key_dir}/seed.lock"
  fi
  if (( rc != 0 )) || [[ "${gpu_cache_cold}" == true ]]; then
    gpu_job_remove_cache_tree "${gpu_cache_run}"
  fi
  {
    flock -x 9
    flock -u "${gpu_cache_run_fd}"
    flock -u "${gpu_cache_key_fd}"
    exec {gpu_cache_run_fd}>&- {gpu_cache_key_fd}<&-
    # Remove identity locks once there are no active jobs or waiters.
    flock -n -E 0 "${gpu_cache_key_dir}" find "${gpu_cache_key_dir}" \
      -maxdepth 1 -name 'run-*.lock' -type f -delete
    gpu_job_prune_cache
  } 9<"${gpu_cache_key_dir%/*}"
  exit "${rc}"
}

gpu_job_cache_dirs() {
  local cache_root="${ISAAC_CI_CACHE_ROOT:-${HOME}/isaac-ci-cache}"
  local key seed stale
  gpu_job_group "Pre-create Isaac Sim cache mount dirs (writable)"
  key="$(gpu_job_cache_key)"
  gpu_cache_key_dir="${cache_root%/}/${key}"
  gpu_cache_run="${gpu_cache_key_dir}/run-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
  seed="${gpu_cache_key_dir}/seed"
  gpu_cache_cold=false
  if gpu_job_cold_cache; then
    gpu_cache_cold=true
  fi

  mkdir -p -- "${cache_root}"
  {
    flock -x 9
    if [[ ! -d "${gpu_cache_key_dir}" ]]; then
      mkdir -m 700 -- "${gpu_cache_key_dir}"
    fi
    exec {gpu_cache_key_fd}<"${gpu_cache_key_dir}"
    flock -s "${gpu_cache_key_fd}"
  } 9<"${cache_root}"

  # Sibling jobs in a workflow share the run ID and attempt. Serialize only
  # jobs that would otherwise mount the same run directory.
  exec {gpu_cache_run_fd}>>"${gpu_cache_run}.lock"
  flock -x "${gpu_cache_run_fd}"
  trap 'gpu_job_finish_cache "$?"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  gpu_job_remove_cache_tree "${gpu_cache_run}"
  while IFS= read -r -d '' stale; do
    {
      if flock -n 8; then
        gpu_job_remove_cache_tree "${stale}"
      fi
    } 8>>"${stale}.lock"
  done < <(find "${gpu_cache_key_dir}" -mindepth 1 -maxdepth 1 -type d \
    -name 'run-*' ! -newermt '1 day ago' -print0)

  mkdir -p -- "${gpu_cache_run}"/{kit-cache,computecache}
  if [[ "${gpu_cache_cold}" == true ]]; then
    echo "cache mode: cold (empty cache dir ${gpu_cache_run})"
  else
    {
      flock -s 9
      if [[ ! -d "${seed}" && -d "${seed}.old" ]]; then
        seed="${seed}.old"
      fi
      if [[ -d "${seed}" ]]; then
        cp -a -- "${seed}/." "${gpu_cache_run}/"
        echo "cache mode: warm (seed copied from ${seed})"
      else
        echo "cache mode: warm (no seed yet)"
      fi
    } 9>>"${gpu_cache_key_dir}/seed.lock"
  fi
  chmod -R a+rwX "${gpu_cache_run}"
  # Let the runner clean up nested directories created by a rootless subuid.
  if command -v setfacl >/dev/null; then
    find "${gpu_cache_run}" -type d -exec setfacl -m "d:u:$(id -u):rwx" {} +
  fi

  mkdir -p \
    isaac-sim/kit/data isaac-sim/kit/logs \
    isaac-sim/ov/cache isaac-sim/ov/data isaac-sim/ov/logs \
    isaac-sim/pip isaac-sim/nvidia/glcache isaac-sim/documents
  rm -rf isaac-sim/kit/cache isaac-sim/nvidia/computecache
  ln -sr -- "${gpu_cache_run}/kit-cache" isaac-sim/kit/cache
  ln -sr -- "${gpu_cache_run}/computecache" isaac-sim/nvidia/computecache

  # Rootless Docker: the container's non-root user maps to a subuid on the
  # host, so files owned by the runner are not writable inside the container.
  # chmod a+rwX makes the workspace (repo root, cache dirs, test-report dir)
  # accessible for any uid.  The runner user keeps ownership, so host-side
  # steps (setup.sh apply, git) still work.  Harmless on a rootful daemon.
  # See ycpss91255-lab/.github#38, isaac#314.
  # An overridden cache root may be inside the checkout. Only its run copy
  # should have its permissions widened.
  find "${GITHUB_WORKSPACE:?}" -samefile "${cache_root}" -prune -o \
    ! -type l -exec chmod a+rwX -- {} +
  gpu_job_endgroup
}
