#!/usr/bin/env bash
set -euo pipefail

# gpu_integration_job.sh runs from the checkout where setup wrote the image tag.
# shellcheck source=/dev/null
. ./.env.generated

artifacts="${PWD}/artifacts/pythontests"
mkdir -p "${artifacts}"
status=0
for bucket in asset deprecated; do
  report="${artifacts}/${bucket}.xml"
  container_report="/artifacts/${bucket}.xml"
  # Bind a fresh writable file for the image's non-root user on rootless Docker.
  # Keep the bind outside sticky /tmp so another UID can open it for writing.
  : > "${report}"
  chmod a+rw "${report}"

  # The asset scripts write relative to their working directory.
  docker_status=0
  docker run --rm --gpus all \
    --label "com.docker.compose.project=${BASELINE_PROJECT:?}" \
    -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y \
    --workdir /tmp \
    -v "${PWD}/isaac-sim/kit/cache:/isaac-sim/kit/cache" \
    -v "${report}:${container_report}" \
    --entrypoint python3 "${DOCKER_HUB_USER:?}/${IMAGE_NAME:?}:test" \
    /isaac-sim/run_tests.py --suite pythontests --bucket "${bucket}" \
    --output "${container_report}" || docker_status=$?
  if (( docker_status != 0 )); then
    echo "${bucket}: Docker exited with status ${docker_status}" >&2
    status=1
  fi

  # The upstream runner can exit zero for a failure. Always check the report
  # and continue to the second bucket so both results are available.
  python3 - "${bucket}" "${report}" <<'PY' || status=1
import sys
import xml.etree.ElementTree as ET

bucket, path = sys.argv[1:]
minimum = {"asset": 17, "deprecated": 2}[bucket]
try:
    suite = ET.parse(path).getroot()
    if suite.tag != "testsuite" or suite.get("name") != f"pythontests.{bucket}":
        raise ValueError(f"expected testsuite pythontests.{bucket}")
    total = int(suite.attrib["tests"])
    cases = suite.findall("testcase")
    if total != len(cases) or total < minimum:
        raise ValueError(f"expected at least {minimum} cases with matching totals, got {total}/{len(cases)}")
    failures = int(suite.attrib["failures"])
    errors = int(suite.attrib["errors"])
    skipped = int(suite.get("skipped", "0"))
    for tag, count in (("failure", failures), ("error", errors), ("skipped", skipped)):
        if len(suite.findall(f"testcase/{tag}")) != count:
            raise ValueError(f"inconsistent {tag} count")
    seconds = float(suite.attrib["time"])
except (OSError, ET.ParseError, ValueError, KeyError) as exc:
    sys.exit(f"Invalid pythontests report for {bucket}: {exc}")

print(f"{bucket}: {total - failures - errors - skipped}/{total} passed in {seconds:.1f}s"
      f" (failures={failures}, errors={errors}, skipped={skipped})")
sys.exit(int(any((failures, errors, skipped))))
PY
done

exit "${status}"
