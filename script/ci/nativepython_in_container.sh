#!/usr/bin/env bash
set -euo pipefail

cd "${1:?Isaac Sim directory required}"
sim_dir="${PWD}"
artifacts="$(realpath "${2:?Artifact directory required}")"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

# Exercise the repo's SimulationApp launch config through its existing Kit
# probe. Kit can terminate with exit zero, so require the in-app marker too.
usd="${work_dir}/probe.usda"
cat > "${usd}" <<'USD'
#usda 1.0
(
    upAxis = "Z"
    metersPerUnit = 1
)
def Xform "World"
{
}
USD
rc=0
ISAAC_LIVESTREAM='' ISAAC_KIT_EXTRA_ARGS="--/app/isaac_test/marker=1" \
  ./python.sh /workspace/test/integration/pytest/_kit_extra_args_runner.py \
  --script-dir /workspace/framework --usd-path "${usd}" 2>&1 \
  | tee "${artifacts}/driver.log" || rc=$?
if ! grep -Fxq '[MARKER] 1' "${artifacts}/driver.log"; then
  echo "IsaacDriver launch did not reach the Kit settings probe" >&2
  if (( rc == 0 )); then rc=1; fi
fi

bucket_rc=0
# Replicator writes render output relative to the working directory.
mkdir "${work_dir}/bucket"
(
  cd "${work_dir}/bucket" || exit
  python3 "${sim_dir}/run_tests.py" --suite nativepythontests --bucket testing \
    --output "${artifacts}/testing.xml"
) || bucket_rc=$?
if (( rc == 0 )); then rc=${bucket_rc}; fi

# The upstream runner can return zero despite reporting failures in JUnit.
report_rc=0
python3 - "${artifacts}/testing.xml" <<'PY' || report_rc=$?
import sys
import xml.etree.ElementTree as ET

try:
    suite = ET.parse(sys.argv[1]).getroot()
    cases = suite.findall("testcase")
    if (suite.tag != "testsuite" or suite.get("name") != "nativepythontests.testing"
            or int(suite.attrib["tests"]) != 41 or len(cases) != 41):
        raise ValueError("expected 41 nativepythontests.testing cases")
    failed = [case.get("name") for case in cases
              if any(result.tag in {"failure", "error", "skipped"} for result in case)]
    if failed or int(suite.attrib["failures"]) or int(suite.attrib["errors"]):
        sys.exit(f"Official nativepython failures: {', '.join(failed)}")
    print("OK: nativepythontests.testing 41 passed")
except (OSError, ET.ParseError, ValueError, KeyError) as exc:
    sys.exit(f"Invalid nativepython JUnit report: {exc}")
PY
if (( rc == 0 )); then rc=${report_rc}; fi

# Run both examples even if the bucket or the first example fails.
for example in livestream hello_world; do
  example_rc=0
  bash "tests/tests-nativepython-isaacsim.simulation_app.${example}.sh" 2>&1 \
    | tee "${artifacts}/${example}.log" || example_rc=$?
  echo "${example}: exit ${example_rc}"
  if (( rc == 0 )); then rc=${example_rc}; fi
done
exit "${rc}"
