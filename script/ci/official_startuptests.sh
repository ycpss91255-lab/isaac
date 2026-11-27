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

# run_tests.py can exit zero even when a startup test failed.
python3 - "${artifacts}/r.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
try:
    root = ET.parse(path).getroot()
    if root.tag != "testsuite" and (
        root.tag != "testsuites" or root.find(".//testsuite") is None
    ):
        raise ValueError("expected a JUnit report containing a testsuite")

    for suite in root.iter():
        if suite.tag not in ("testsuite", "testsuites"):
            continue
        for field in ("failures", "errors"):
            # Wrapper totals are optional. The official suite reports both counts.
            if suite.tag == "testsuites" and field not in suite.attrib:
                continue
            count = int(suite.attrib[field])
            if count != 0:
                name = suite.get("name", suite.tag)
                sys.exit(f"{path}: {name} reports {field}={count}")
except (OSError, ET.ParseError, ValueError, KeyError) as exc:
    sys.exit(f"Invalid startup JUnit report {path}: {exc}")
PY
