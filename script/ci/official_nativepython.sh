#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=/dev/null
. ./.env.generated
artifacts="${PWD}/artifacts/official-nativepython"
mkdir -p "${artifacts}"
chmod a+rx "${artifacts}"
# Clear any report from an earlier local run before starting Docker.
for file in testing.xml livestream.log hello_world.log driver.log; do
  rm -f "${artifacts}/${file}"
  touch "${artifacts}/${file}"
  chmod a+rw "${artifacts}/${file}"
done

probe="test/integration/pytest/_kit_extra_args_runner.py"
timing_helper="test/integration/pytest/_kit_boot.py"

# Bridge networking lets the upstream scripts install their pip requirements.
docker run --rm --gpus all --network bridge \
  --label "com.docker.compose.project=${BASELINE_PROJECT:?}" \
  --tmpfs /isaac-sim/_testoutput:mode=1777 \
  -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y -e CASE_TIMEOUT_SECONDS \
  -v "${PWD}/isaac-sim/kit/cache:/isaac-sim/kit/cache" \
  -v "${artifacts}:/artifacts" \
  -v "${PWD}/framework:/workspace/framework:ro" \
  -v "${PWD}/${probe}:/workspace/${probe}:ro" \
  -v "${PWD}/${timing_helper}:/workspace/${timing_helper}:ro" \
  -v "${PWD}/script/ci/bucket_watchdog.py:/tmp/bucket_watchdog.py:ro" \
  -v "${PWD}/script/ci/nativepython_in_container.sh:/tmp/nativepython_in_container.sh:ro" \
  --entrypoint bash "${DOCKER_HUB_USER:?}/${IMAGE_NAME:?}:headless" \
  /tmp/nativepython_in_container.sh /isaac-sim /artifacts
