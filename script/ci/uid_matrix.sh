#!/usr/bin/env bash
# Build the selected stage with representative host identities and check their access.
set -euo pipefail

UID_MATRIX_TARGET="${UID_MATRIX_TARGET:-devel-base}"
dry_run=false
gpu=true
for arg in "$@"; do
  case "${arg}" in
    --dry-run) dry_run=true ;;
    --no-gpu) gpu=false ;;
    --help|-h)
      echo 'Usage: uid_matrix.sh [--dry-run] [--no-gpu]'
      echo 'UID_MATRIX_TARGET selects the build stage (default: devel-base). Set it to devel for the full build.'
      echo 'BASE_IMAGE overrides the pinned Dockerfile base. --dry-run prints commands.'
      echo '--no-gpu skips the GPU import and checks identity, sudo and permissions.'
      exit 0 ;;
    *) echo "Unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

docker_cmd() {
  if "${dry_run}"; then
    printf '%q ' docker "$@"
    printf '\n'
  else
    docker "$@"
  fi
}

base_args=()
if [[ -n "${BASE_IMAGE:-}" ]]; then
  base_args=(--build-arg "BASE_IMAGE=${BASE_IMAGE}")
fi

# The positional arguments to bash -c are the expected host name, UID and GID.
# shellcheck disable=SC2016  # Expanded inside the container.
probe='
  [[ "$(id -un)" == "$1" && "$(id -u)" == "$2" && "$(id -g)" == "$3" ]]
  sudo -n true
  grep -qw "$(cat /etc/isaac/base-gid)" <<< "$(id -G)"
  [[ "$HOME" == "/home/$1" && -w "$HOME" ]]
  ls /isaac-sim >/dev/null
  for dir in /isaac-sim/exts/isaacsim.asset.importer.mjcf{,.ui}/data \
             /isaac-sim/exts/isaacsim.asset.importer.mjcf/data/mjcf \
             /isaac-sim/kit/data /isaac-sim/kit/cache /isaac-sim/_testoutput; do
    [[ -d "${dir}" ]] || continue
    test -w "${dir}"
    touch "${dir}/.uid-matrix-$$"
    rm "${dir}/.uid-matrix-$$"
  done
  if [[ -n "${ISAACLAB_PATH:-}" ]]; then ls "$ISAACLAB_PATH" >/dev/null; fi'

gpu_args=(--env NVIDIA_VISIBLE_DEVICES=void)
if "${gpu}"; then
  gpu_args=(--gpus all --env ACCEPT_EULA=Y)
  probe+=$'\n  /isaac-sim/python.sh -c "import isaacsim"'
fi

run_id="$$-${RANDOM}"
conflict_gid=1234
if [[ "${BASE_IMAGE:-}" == *isaac-lab* ]]; then
  conflict_gid=1000
fi
for pair in 1000:1000 1234:1234 50000:50000 "50000:${conflict_gid}"; do
  uid="${pair%:*}"
  gid="${pair#*:}"
  tag="ycpss91255/cc-uid-${uid}-${gid}:${run_id}"
  name="cc-rv474-${uid}-${gid}-${run_id}"
  # --rm handles normal exits. Reap only this case on failure or interruption.
  trap 'docker_cmd rm -f "${name}" >/dev/null 2>&1 || true
        docker_cmd image rm "${tag}" >/dev/null 2>&1 || true' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  docker_cmd build --target "${UID_MATRIX_TARGET}" --tag "${tag}" "${base_args[@]}" \
    --build-arg USER_NAME=uidcheck --build-arg "USER_UID=${uid}" \
    --build-arg "USER_GID=${gid}" .
  docker_cmd image inspect --format "Image size (${tag}): {{.Size}} bytes" "${tag}"
  run_args=(--entrypoint /bin/bash)
  shell_args=()
  if [[ "${UID_MATRIX_TARGET}" != devel ]]; then
    run_args=(--user "${uid}:${gid}" -e HOME=/home/uidcheck --entrypoint /usr/bin/sudo)
    # Docker omits supplementary groups with an explicit GID. Reload the
    # image's groups before running the probe as the requested UID and GID.
    shell_args=(-n -E -- setpriv --reuid="${uid}" --regid="${gid}" --init-groups /bin/bash)
  fi
  docker_cmd run --rm --name "${name}" "${gpu_args[@]}" "${run_args[@]}" \
    "${tag}" "${shell_args[@]}" -euxo pipefail -c "${probe}" uid-matrix uidcheck "${uid}" "${gid}"
  docker_cmd image rm "${tag}"
  trap - EXIT INT TERM
done
