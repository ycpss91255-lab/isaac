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
      [[ "${probe}" != *"import isaacsim"* ]]
    else
      [[ "${probe}" == *"--gpus"* ]]
      [[ "${probe#*" ${tag} "}" == *"import isaacsim"* ]]
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

@test "uid_matrix: every devel identity checks, creates and removes a file in each MJCF data directory" {
  # Replay the actual CPU probe against a fixture with the official image layout.
  # Only account lookups and paths specific to the image need substituting.
  export FIXTURE="${BATS_TEST_TMPDIR}/image"
  local ext="${FIXTURE}/isaac-sim/exts/isaacsim.asset.importer.mjcf"
  mkdir -p "${ext}/data/mjcf" "${ext}.ui/data" "${FIXTURE}/home/uidcheck"
  echo 1234 > "${FIXTURE}/base-gid"
  cat > "${BATS_TEST_TMPDIR}/docker" <<'STUB'
#!/usr/bin/env bash
set -eu
[[ "$1" == run ]] || exit 0
while [[ "$1" != -c ]]; do shift; done
shift
probe="${1//\/home\//${FIXTURE}\/home\/}"
probe="${probe//\/etc\/isaac\/base-gid/${FIXTURE}\/base-gid}"
probe="${probe//\/isaac-sim/${FIXTURE}\/isaac-sim}"
shift
export HOME="${FIXTURE}/home/$2" CASE_UID="$3" CASE_GID="$4"
id() {
  case "$1" in
    -un) echo uidcheck ;;
    -u) echo "${CASE_UID}" ;;
    -g) echo "${CASE_GID}" ;;
    -G) echo "${CASE_GID} 1234" ;;
    *) return 1 ;;
  esac
}
sudo() { [[ "$*" == "-n true" ]]; }
export -f id sudo
bash -euxo pipefail -c "${probe}" "$@" 2>"${FIXTURE}/trace-${CASE_UID}-${CASE_GID}"
STUB
  unset ISAACLAB_PATH
  export BASE_IMAGE=nvcr.io/nvidia/isaac-sim:6.2.0.1 UID_MATRIX_TARGET=devel
  run bash "${SCRIPT}" --no-gpu
  [ "${status}" -eq 0 ]
  local pair dir trace
  for pair in 1000-1000 1234-1234 50000-50000 50000-1234; do
    trace="${FIXTURE}/trace-${pair}"
    for dir in "${ext}/data" "${ext}/data/mjcf" "${ext}.ui/data"; do
      # Bash xtrace expands loop variables, so checks for HOME or a sibling
      # directory cannot satisfy the assertion for this write parent.
      awk -v dir="${dir}" '
        { for (i = 2; i <= NF; i++) {
            if ($(i-1) == "-w" && $i == dir) writable = 1
            if (index($i, dir "/") == 1 && substr($i, length(dir)+2) !~ /\//) {
              if ($2 == "touch") created[$i] = 1
              if ($2 == "rm" && created[$i]) removed = 1
            }
        } }
        END { exit !(writable && removed) }
      ' "${trace}" || { echo "Missing MJCF write probe for ${pair} in ${dir}"; return 1; }
    done
  done
  [ -z "$(find "${ext}/data" "${ext}.ui/data" -type f -print -quit)" ]
}

@test "core-gpu: a failing GPU UID matrix fails the integration job" {
  local src fake
  src="$(dirname "${SCRIPT}")"
  fake="${BATS_TEST_TMPDIR}/repo"
  mkdir -p "${fake}/script/ci" "${fake}/test"
  cp "${src}/gpu_job_lib.sh" "${src}/gpu_integration_job.sh" "${fake}/script/ci/"
  printf '#!/bin/sh\necho WS_PATH=/tmp > .env.generated\n' > "${fake}/script/setup.sh"
  printf '#!/bin/sh\nexit 0\n' > "${fake}/script/build.sh"
  cp "${fake}/script/build.sh" "${fake}/test/assert_pytest_baseline.sh"
  cat > "${fake}/script/ci/uid_matrix.sh" <<'STUB'
#!/bin/sh
echo "matrix argc=$#"
exit 17
STUB
  chmod +x "${fake}"/script/*.sh "${fake}"/script/ci/*.sh "${fake}"/test/*.sh
  GITHUB_WORKSPACE="${fake}" GITHUB_RUN_ID=1234 GITHUB_RUN_ATTEMPT=1 \
    run bash "${fake}/script/ci/gpu_integration_job.sh"
  [[ "${output}" == *"matrix argc=0"* ]]
  [ "${status}" -ne 0 ]
}
