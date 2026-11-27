#!/usr/bin/env bats
# bats file_tags=core
# Exercise the host CLI and its printed Docker commands without a daemon.

bats_require_minimum_version 1.5.0

setup() {
  SCRIPT="${BATS_TEST_DIRNAME}/uid_matrix.sh"
  if [[ ! -f "${SCRIPT}" ]]; then
    SCRIPT="${BATS_TEST_DIRNAME}/../../../script/ci/uid_matrix.sh"
  fi
  [ -f "${SCRIPT}" ]

  export DOCKER_LOG="${BATS_TEST_TMPDIR}/docker.log"
  export DOCKER_HOST="unix://${BATS_TEST_TMPDIR}/no-docker.sock"
  cat > "${BATS_TEST_TMPDIR}/docker" <<'STUB'
#!/bin/sh
echo "$*" >> "${DOCKER_LOG}"
exit 99
STUB
  chmod +x "${BATS_TEST_TMPDIR}/docker"
  export PATH="${BATS_TEST_TMPDIR}:${PATH}"
}

@test "uid_matrix: --help prints usage without Docker" {
  run bash "${SCRIPT}" --help
  [ "${status}" -eq 0 ]
  [[ "${output,,}" == *usage* ]]
  [[ "${output}" == *UID_MATRIX_TARGET*devel-base* ]]
  [ ! -e "${DOCKER_LOG}" ]
}

@test "uid_matrix: an unknown option fails before any Docker call" {
  run bash "${SCRIPT}" --unknown-option
  [ "${status}" -ne 0 ]
  [ ! -e "${DOCKER_LOG}" ]
}

# Check each run against the image built for its UID:GID. Match command
# lines, so a case banner or a probe printed for a different image cannot pass.
check_plan() {
  local target="$1"
  local plan build probe tag user uid gid
  local tag_flag='(-t|--tag)[= ]+(ycpss91255/cc-uid-[[:alnum:]_.:-]+)'
  local user_arg='--build-arg[= ]+USER_NAME=([[:alnum:]_.-]+)'
  local uid_arg='--build-arg[= ]+USER_UID=([[:digit:]]+)([[:space:]]|$)'
  local gid_arg='--build-arg[= ]+USER_GID=([[:digit:]]+)([[:space:]]|$)'
  local -a builds probes
  local -A cases=()
  # Accept both plain commands and shell-quoted argv (e.g. printf %q).
  plan="$(printf '%s\n' "${output}" | tr -d "\"'\\\\")"
  mapfile -t builds < <(printf '%s\n' "${plan}" | grep -E 'docker (buildx )?build ')
  [ "${#builds[@]}" -eq 4 ]
  for build in "${builds[@]}"; do
    [[ "${build}" =~ ${uid_arg} ]]
    uid="${BASH_REMATCH[1]}"
    [[ "${build}" =~ ${gid_arg} ]]
    gid="${BASH_REMATCH[1]}"
    cases["${uid}:${gid}"]=1
    [[ "${build}" =~ --target[=[:space:]]+"${target}"([[:space:]]|$) ]]
    [[ " ${build} " == *" --build-arg BASE_IMAGE=${BASE_IMAGE} "* ||
       " ${build} " == *" --build-arg=BASE_IMAGE=${BASE_IMAGE} "* ]]
    [[ "${build}" =~ ${user_arg} ]]
    user="${BASH_REMATCH[1]}"
    [[ "${build}" =~ ${tag_flag} ]]
    tag="${BASH_REMATCH[2]}"

    mapfile -t probes < <(printf '%s\n' "${plan}" | sed -n 's/.*docker run //p' | grep -F " ${tag} ")
    [ "${#probes[@]}" -eq 1 ]
    probe="${probes[0]}"
    [[ " ${probe} " == *" --rm "* ]]
    [[ "${probe}" =~ --name[=[:space:]]+cc-rv474- ]]
    if [[ "${target}" == devel ]]; then
      [[ " ${probe} " != *" --user "* && " ${probe} " != *" HOME=/home/uidcheck "* ]]
    else
      [[ " ${probe} " == *" --user ${uid}:${gid} "* ]]
      [[ " ${probe} " == *" -e HOME=/home/uidcheck "* ]]
    fi
    if [[ "${2:-}" == --no-gpu ]]; then
      [[ "${probe}" != *"--gpus"* && "${probe}" != *"--runtime=nvidia"* ]]
    fi
    # Inspect the command after the image tag. Build arguments and the
    # outer docker run flags cannot satisfy the in-container assertions.
    probe="${probe#*" ${tag} "}"
    [[ "${probe}" == *"id -un"* ]]
    [[ "${probe}" =~ [[:space:]](=|==|!=)[[:space:]] ]]
    [[ "${probe}" == *"${user}"* || "${probe}" == *'USER_NAME'* ]]
    [[ "${probe}" == *"sudo -n true"* ]]
    [[ "${probe}" == *"id -G"* ]]
    [[ "${probe,,}" == *gid* || "${probe}" == *'stat -c %g'* ]]
    [[ "${probe}" =~ grep|case|=~|for[[:space:]] || "${probe}" == *'=='*'*'* ]]
    [[ "${probe}" =~ ls[[:space:]]+[^\;\&\|]*(/isaac-sim|/workspace/isaaclab|\$) ]]
  done
  [ "${cases[1000:1000]}" = 1 ]
  [ "${cases[1234:1234]}" = 1 ]
  [ "${cases[50000:50000]}" = 1 ]
  [[ "${cases[50000:1234]:-}" == 1 || "${cases[50000:1000]:-}" == 1 ]]
}

@test "uid_matrix: dry-run plans each host identity on the Sim base" {
  unset UID_MATRIX_TARGET
  export BASE_IMAGE=nvcr.io/nvidia/isaac-sim:6.2.0.1
  run bash "${SCRIPT}" --dry-run
  [ "${status}" -eq 0 ]
  [ ! -e "${DOCKER_LOG}" ]
  check_plan devel-base
}

@test "uid_matrix: --no-gpu dry-run honors the Lab base and devel target overrides" {
  export BASE_IMAGE=nvcr.io/nvidia/isaac-lab:3.0.0
  export UID_MATRIX_TARGET=devel
  run bash "${SCRIPT}" --no-gpu --dry-run
  [ "${status}" -eq 0 ]
  [ ! -e "${DOCKER_LOG}" ]
  check_plan devel --no-gpu
}
