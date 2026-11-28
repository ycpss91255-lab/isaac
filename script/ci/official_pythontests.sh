#!/usr/bin/env bash
set -euo pipefail

# gpu_integration_job.sh runs from the checkout where setup wrote the image tag.
# shellcheck source=/dev/null
. ./.env.generated

artifacts="${PWD}/artifacts/pythontests"
mkdir -p "${artifacts}"
status=0
for bucket in asset deprecated core sensors; do
  report="${artifacts}/${bucket}.xml"
  container_report="/artifacts/${bucket}.xml"
  kit_output="$(mktemp -d "${artifacts}/${bucket}.XXXXXX")"
  chmod a+rwx "${kit_output}"
  script_args="--/exts/omni.kit.test/testExtOutputPath=/artifacts/kit-logs"
  if [[ "${bucket}" == sensors ]]; then
    # Keep the RTX extension's two upstream excludes at indices 0 and 1.
    tiled_case='isaacsim.sensors.experimental.rtx.tests.test_tiled_camera_sensor.TestTiledCameraSensor.test_tiled_data'
    script_args+=" \"--/exts/omni.kit.test/testExtArgs/2=--/exts/omni.kit.test/excludeTests/2='${tiled_case}'\""
  fi
  # Bind a fresh writable file for the image's non-root user on rootless Docker.
  # Keep the bind outside sticky /tmp so another UID can open it for writing.
  : > "${report}"
  chmod a+rw "${report}"

  # The asset scripts write relative to their working directory.
  docker_status=0
  docker run --rm --name "cc-${BASELINE_PROJECT:?}-${bucket}" --gpus all \
    --label "com.docker.compose.project=${BASELINE_PROJECT:?}" \
    -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y \
    --workdir /tmp \
    -v "${PWD}/isaac-sim/kit/cache:/isaac-sim/kit/cache" \
    -v "${report}:${container_report}" \
    -v "${kit_output}:/artifacts/kit-logs" \
    --entrypoint python3 "${DOCKER_HUB_USER:?}/${IMAGE_NAME:?}:test" \
    /isaac-sim/run_tests.py --suite pythontests --bucket "${bucket}" \
    --output "${container_report}" --script-args="${script_args}" || docker_status=$?
  if (( docker_status != 0 )); then
    echo "${bucket}: Docker exited with status ${docker_status}" >&2
    status=1
  fi

  # The upstream runner can exit zero for a failure. Always check the report
  # and continue through the remaining buckets so both results are available.
  python3 "${BASH_SOURCE[0]%/*}/check_official_pythontests.py" \
    "${bucket}" "${report}" "${kit_output}" || status=1
done

exit "${status}"
