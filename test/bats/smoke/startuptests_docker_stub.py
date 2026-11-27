#!/usr/bin/env python3
"""Docker stand-in for gpu_job_scripts_spec.bats. Only bind-mounted output survives --rm."""

import argparse
import os
import shlex
import sys
from pathlib import Path


def write_mounted_file(mounts, path, content):
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    for target, source in mounts:
        if target == path or target in path.parents:
            dest = (source / path.relative_to(target)).resolve()
            assert workspace in dest.parents, f"unexpected fixture write outside {workspace}: {dest}"
            if target == path:
                assert source.is_file(), f"a single-file bind needs an existing file: {source}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content + "\n")
            return


def main(args):
    with open(os.environ["CALLS"], "a") as calls:
        print("docker", shlex.join(args), file=calls)
    assert args[0] == "run", args
    image, shell, option, command = args[-4:]
    assert image == "alice/isaac:test", image
    assert (shell, option) == ("bash", "-c")
    assert command == "cd /isaac-sim && python3 run_tests.py --suite startuptests --output /tmp/r.xml"

    flags = argparse.ArgumentParser()
    flags.add_argument("--rm", required=True, action="store_true")
    flags.add_argument("--gpus", choices=["all"], required=True)
    flags.add_argument("-e", "--env", action="append", default=[])
    flags.add_argument("-v", "--volume", action="append", default=[])
    flags.add_argument("--mount", action="append", default=[])
    options, extra = flags.parse_known_args(args[1:-4])
    assert "-d" not in extra and "--detach" not in extra
    assert {"ACCEPT_EULA=Y", "PRIVACY_CONSENT=Y"} <= set(options.env), options.env

    mounts = []
    for volume in options.volume:
        source, target, *mode = volume.split(":")
        if not mode or "ro" not in mode[0].split(","):
            mounts.append((Path(target), Path(source)))
    for mount in options.mount:
        parts = mount.split(",")
        fields = dict(item.split("=", 1) for item in parts if "=" in item)
        if fields.get("type") == "bind" and not {"ro", "readonly"}.intersection(parts):
            source = fields.get("source") or fields["src"]
            target = fields.get("target") or fields.get("dst") or fields["destination"]
            mounts.append((Path(target), Path(source)))

    rc = int(os.environ.get("STARTUP_RC", "0"))
    report = f'<testsuite name="startup-fixture" failures="{int(rc != 0)}"/>'
    write_mounted_file(mounts, Path("/tmp/r.xml"), report)
    if rc:
        log = Path("/isaac-sim/kit/logs/Kit/Isaac-Sim/6.2/kit_20261120_123456.log")
        write_mounted_file(mounts, log, "Kit startup failure from this run")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
