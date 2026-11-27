#!/usr/bin/env bash
set -euo pipefail

# gpu_integration_job.sh runs from the checkout where setup wrote the image tag.
# shellcheck source=/dev/null
. ./.env.generated

artifacts="${PWD}/artifacts/startuptests"
mkdir -p "${artifacts}/kit-logs"
# Pre-create writable binds for the image's non-root user on rootless Docker.
: > "${artifacts}/r.xml"
chmod a+rw "${artifacts}/r.xml"
chmod a+rwx "${artifacts}/kit-logs"

docker run --rm --gpus all \
  --label "com.docker.compose.project=${BASELINE_PROJECT:?}" \
  -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y \
  -v "${PWD}/isaac-sim/kit/cache:/isaac-sim/kit/cache" \
  -v "${artifacts}/kit-logs:/artifacts/kit-logs" \
  -v "${artifacts}/r.xml:/tmp/r.xml" \
  -v "${PWD}/script/ci/startuptests_in_container.sh:/tmp/startuptests_in_container.sh:ro" \
  "${DOCKER_HUB_USER:?}/${IMAGE_NAME:?}:test" \
  bash /tmp/startuptests_in_container.sh

test -s "${artifacts}/r.xml"
