#!/usr/bin/env python3
"""Run the startup job's container command against a disposable fixture filesystem."""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Bash executes the real command and mounted script unchanged. Redirect absolute
# operands of the commands they use into the fixture without requiring chroot.
BASH_ENV = """\
fixture_command() {
  local cmd="$1" arg
  shift
  local -a args=()
  for arg in "$@"; do
    case "${arg}" in
      "${FIXTURE_ROOT}"/*) args+=("${arg}") ;;
      /*) args+=("${FIXTURE_ROOT}${arg}") ;;
      *) args+=("${arg}") ;;
    esac
  done
  command "${cmd}" "${args[@]}"
}
cd() { fixture_command cd "$@"; }
python3() { fixture_command python3 "$@"; }
mkdir() { fixture_command mkdir "$@"; }
cp() { fixture_command cp "$@"; }
bash() { fixture_command bash "$@"; }
"""

RUN_TESTS = """\
import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--suite", choices=["startuptests"], required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
rc = int(os.environ.get("STARTUP_RC", "0"))
failures = int(os.environ.get("STARTUP_JUNIT_FAILURES", int(rc != 0)))
errors = int(os.environ.get("STARTUP_JUNIT_ERRORS", "0"))
suite = ET.Element("testsuite", name="startuptests.default", tests="4",
                   failures=str(failures), errors=str(errors))
main = ET.SubElement(suite, "testcase", name="tests-startup.main.sh")
if failures:
    ET.SubElement(main, "failure", message=f"Exit code: {rc or 55}")
for index in range(1, 4):
    case = ET.SubElement(suite, "testcase", name=f"startup-fixture-{index}")
    if index <= errors:
        ET.SubElement(case, "error", message="Startup error")

report = suite
if os.environ.get("STARTUP_JUNIT_WRAPPED") == "1":
    report = ET.Element("testsuites")
    report.append(suite)
xml = ET.tostring(report, encoding="unicode")
if os.environ.get("STARTUP_JUNIT_TRUNCATED") == "1":
    xml = xml[:xml.rindex("</")]
args.output.write_text(xml + "\\n")

log = (Path.home() / ".nvidia-omniverse/logs/Kit/Isaac-Sim Streaming (Newton)"
       / "6.2/kit_20261127_162941.log")
log.parent.mkdir(parents=True)
log.write_text(f"Kit startup fixture rc={rc}\\n")
raise SystemExit(rc)
"""


def bind_mounts(options):
    for volume in options.volume:
        source, target, *mode = volume.split(":")
        yield Path(source), Path(target), bool(mode and "ro" in mode[0].split(","))
    for mount in options.mount:
        parts = mount.split(",")
        fields = dict(item.split("=", 1) for item in parts if "=" in item)
        assert fields.get("type") == "bind", mount
        source = fields.get("source") or fields["src"]
        target = fields.get("target") or fields.get("dst") or fields["destination"]
        yield Path(source), Path(target), bool({"ro", "readonly"}.intersection(parts))


def main(args):
    with open(os.environ["CALLS"], "a") as calls:
        print("docker", shlex.join(args), file=calls)
    assert args[0] == "run", args
    flags = argparse.ArgumentParser()
    flags.add_argument("--rm", required=True, action="store_true")
    flags.add_argument("--gpus", choices=["all"], required=True)
    flags.add_argument("--label", action="append")
    flags.add_argument("-e", "--env", action="append", default=[])
    flags.add_argument("-v", "--volume", action="append", default=[])
    flags.add_argument("--mount", action="append", default=[])
    flags.add_argument("image", choices=["alice/isaac:test"])
    flags.add_argument("command", nargs=argparse.REMAINDER)
    options = flags.parse_args(args[1:])
    assert {"ACCEPT_EULA=Y", "PRIVACY_CONSENT=Y"} <= set(options.env), options.env

    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for directory in ("isaac-sim", "tmp", "home/kit"):
            (root / directory).mkdir(parents=True)
        (root / "isaac-sim/run_tests.py").write_text(RUN_TESTS)
        init = root / "bash_env"
        init.write_text(BASH_ENV)

        for source, target, readonly in bind_mounts(options):
            assert workspace in source.resolve().parents and source.exists(), source
            dest = root / target.relative_to("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == ".sh":
                assert readonly, f"container script must be mounted read-only: {source}"
            if readonly:
                # Only writable binds can persist output in the workspace.
                if source.is_dir():
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)
            else:
                dest.symlink_to(source)

        env = dict(os.environ, HOME=str(root / "home/kit"), FIXTURE_ROOT=temp, BASH_ENV=str(init))
        executable, *argv = options.command
        # A script passed directly to Bash is opened before our shell functions run.
        if executable in ("bash", "/bin/bash"):
            if argv and argv[0].startswith("/"):
                argv[0] = str(root / argv[0].lstrip("/"))
        else:
            executable = root / Path(executable).relative_to("/")
        return subprocess.run([executable, *argv], cwd=root, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
