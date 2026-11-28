#!/usr/bin/env bats
# bats file_tags=core
#
# Guard: every reusable-workflow reference to the org's gpu-self-hosted.yml
# must use a release tag at or above GPU_REUSABLE_MIN_TAG.
# test_workflow_pins.py is the authoritative structural guard for these pins.
#
# Motivation: when .github's main branch is broken even briefly, every isaac
# push/PR that reaches core-gpu or stream-smoke fails with "workflow
# file issue" and 0 jobs (run 42776185240, 2026-11-10).  Pinning to a release
# tag insulates callers from upstream breakage.  Dependabot (github-actions
# ecosystem, weekly) creates bump PRs when a new tag is cut, so we still
# advance -- just deliberately.
#
# The base build-worker.yaml and release-worker.yaml references are already
# pinned (e.g. @v0.42.0); this spec covers gpu-self-hosted.yml.

bats_require_minimum_version 1.5.0

setup() {
  # Repo checkout: test/bats/smoke/ -> repo root.  devel-test image: the
  # Dockerfile bakes .github/workflows/ next to the specs (isaac#402).
  if [ -d "${BATS_TEST_DIRNAME}/../../../.github/workflows" ]; then
    WORKFLOW_DIR="${BATS_TEST_DIRNAME}/../../../.github/workflows"
  else
    WORKFLOW_DIR="${BATS_TEST_DIRNAME}/workflows"
  fi
  # A missing directory must fail, never pass vacuously.
  [ -d "${WORKFLOW_DIR}" ]
}

_gpu_reusable_min_tag() {
  local source="${BATS_TEST_DIRNAME}/../../../test/unit/pytest/gpu_pin.py" tag
  if [ "${WORKFLOW_DIR}" = "${BATS_TEST_DIRNAME}/workflows" ]; then
    source="${BATS_TEST_DIRNAME}/gpu_pin.py"
  fi
  if ! tag=$(sed -n 's/^GPU_REUSABLE_MIN_TAG[[:space:]]*=[[:space:]]*"\([^"]\{1,\}\)".*$/\1/p' "${source}") || [ -z "${tag}" ]; then
    echo "Could not read GPU_REUSABLE_MIN_TAG from ${source}" >&2
    return 1
  fi
  printf '%s\n' "${tag}"
}

_tag_at_least_min() {
  local LC_ALL=C component='(0|[1-9][0-9]*)' i
  local release="^v${component}\.${component}\.${component}$"
  [[ $1 =~ ${release} ]] || return 1
  local -a version=("${BASH_REMATCH[@]}")
  [[ $2 =~ ${release} ]] || return 1
  local -a minimum=("${BASH_REMATCH[@]}")
  for i in 1 2 3; do
    [[ ${version[i]} == "${minimum[i]}" ]] && continue
    # Compare digit counts first so large components cannot overflow Bash arithmetic.
    if (( ${#version[i]} != ${#minimum[i]} )); then
      (( ${#version[i]} > ${#minimum[i]} ))
    else
      [[ ${version[i]} > ${minimum[i]} ]]
    fi
    return
  done
  return 0
}

@test "no workflow references gpu-self-hosted.yml@main" {
  # Collect every 'uses:' line that references gpu-self-hosted.yml@main.
  local hits
  hits=$(grep -rn 'gpu-self-hosted\.yml@main' "${WORKFLOW_DIR}/" || true)
  if [ -n "${hits}" ]; then
    echo "Found unpinned gpu-self-hosted.yml@main references:"
    echo "${hits}"
    echo ""
    echo "Use a release tag at or above GPU_REUSABLE_MIN_TAG in gpu_pin.py."
    return 1
  fi
}

@test "every gpu-self-hosted.yml caller meets the minimum release tag" {
  local f minimum refs ref
  minimum=$(_gpu_reusable_min_tag)
  for f in main.yaml ci-stream-smoke.yaml ci-headless-smoke.yaml publish-stream-source.yaml; do
    grep -Fq 'gpu-self-hosted.yml@' "${WORKFLOW_DIR}/${f}" \
      || { echo "missing gpu-self-hosted.yml reference in ${f}"; return 1; }
  done
  # Include every occurrence in the required callers and in other workflows.
  refs=$(grep -rHoE "gpu-self-hosted\.yml@[^[:space:]\"']*" "${WORKFLOW_DIR}/")
  while IFS= read -r ref; do
    _tag_at_least_min "${ref#*:gpu-self-hosted.yml@}" "${minimum}" \
      || { echo "${ref} must use a release tag at or above ${minimum}"; return 1; }
  done <<< "${refs}"
}

# --- isaac#344: run-scoped reap-container-filter on core-gpu ---------
# The reusable's cancel-safe "Remove run containers" step only runs when the
# caller passes reap-container-filter; unset, a cancelled run leaks its
# containers.  The workflow is parsed with a real YAML loader (never grepped),
# so a value under env:, in a comment or in another job cannot satisfy it.

_yaml_python() {
  local py
  for py in /isaac-sim/python.sh python3; do
    if "${py}" -c 'import yaml' >/dev/null 2>&1; then
      echo "${py}"
      return 0
    fi
  done
  return 1
}

# Print one field of the core-gpu job in main.yaml.
_gpu_integration_field() {
  local py
  py="$(_yaml_python)" || { echo "no python with PyYAML"; return 1; }
  "${py}" -c '
import sys, yaml
job = yaml.safe_load(open(sys.argv[1]))["jobs"]["core-gpu"]
field = sys.argv[2]
print(job["uses"] if field == "uses" else job["with"][field])
' "${WORKFLOW_DIR}/main.yaml" "$1"
}

@test "core-gpu passes the run-scoped reap-container-filter" {
  local minimum
  minimum=$(_gpu_reusable_min_tag)
  run _gpu_integration_field uses
  [ "${status}" -eq 0 ]
  [ "${output%%@*}" = "ycpss91255-lab/.github/.github/workflows/gpu-self-hosted.yml" ]
  _tag_at_least_min "${output#*@}" "${minimum}"

  run _gpu_integration_field reap-container-filter
  [ "${status}" -eq 0 ]
  [ "${output}" = 'label=com.docker.compose.project=isaac-baseline-${{ github.run_id }}-${{ github.run_attempt }}' ]
}

@test "reap-container-filter names the BASELINE_PROJECT gpu_integration_job.sh runs" {
  local src fake
  if [ -f "${BATS_TEST_DIRNAME}/gpu_integration_job.sh" ]; then
    src="${BATS_TEST_DIRNAME}"
  else
    src="${BATS_TEST_DIRNAME}/../../../script/ci"
  fi
  fake="$(mktemp -d)"
  mkdir -p "${fake}/script/ci" "${fake}/test"
  cp "${src}/gpu_job_lib.sh" "${src}/gpu_integration_job.sh" "${fake}/script/ci/"
  printf '#!/usr/bin/env bash\nprintf "WS_PATH=/x\\n" > .env.generated\n' > "${fake}/script/setup.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' > "${fake}/script/build.sh"
  cp "${fake}/script/build.sh" "${fake}/script/ci/uid_matrix.sh"
  printf '#!/usr/bin/env bash\necho "${BASELINE_PROJECT}" > "${OBSERVED}"\n' \
    > "${fake}/test/assert_pytest_baseline.sh"
  printf '#!/usr/bin/env bash\ntrue\n' > "${fake}/script/ci/official_startuptests.sh"
  cp "${fake}/script/ci/official_startuptests.sh" "${fake}/script/ci/official_pythontests.sh"
  chmod +x "${fake}"/script/*.sh "${fake}"/script/ci/*.sh "${fake}"/test/*.sh

  ISAAC_CI_CACHE_ROOT="${fake}/ci-cache" GITHUB_WORKSPACE="${fake}" GITHUB_RUN_ID=111 GITHUB_RUN_ATTEMPT=2 \
    OBSERVED="${fake}/observed.txt" \
    bash "${fake}/script/ci/gpu_integration_job.sh" >/dev/null
  local project
  project="$(cat "${fake}/observed.txt")"
  [ -n "${project}" ]

  run _gpu_integration_field reap-container-filter
  [ "${status}" -eq 0 ]
  local rendered="${output}"
  rendered="${rendered//'${{ github.run_id }}'/111}"
  rendered="${rendered//'${{ github.run_attempt }}'/2}"
  [ "${rendered}" = "label=com.docker.compose.project=${project}" ]
  rm -rf "${fake}"
}
