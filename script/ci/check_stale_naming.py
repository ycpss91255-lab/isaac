#!/usr/bin/env python3
"""Check tracked working-tree text for retired Docker commands and config names."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


STALE = re.compile(
    r"(^|[^\w])setup\.conf([^\w-]|$)"
    r"|(^|[^\w-])make[ \t]+(build|run|exec|stop|test)([^\w-]|$)"
    r"|(^|[^\w./-])\./(build|run|exec|stop)\.sh\.?([^\w.-]|$)"
)

EXCLUDED = {
    "script/ci/check_stale_naming.py",
    "test/unit/pytest/test_check_stale_naming.py",
    # These ADRs preserve the original decision alongside an editorial update.
    "src/doc/adr/0005-standalone-with-livestream-as-default-dev-entrypoint.md",
    "src/doc/adr/0007-custom-streaming-experience-for-simulationapp.md",
    "src/doc/adr/0014-sim-runtime-stage-taxonomy-stream-vs-headless.md",
}

NEGATIVE_ASSERTIONS = (
    'refute_output --partial "./build.sh"',
    'refute_output --partial "./run.sh"',
    "no removed ./build.sh hint",
    "not the removed ./build.sh / ./run.sh",
    "not the removed `./build.sh`",
    "and no `.setup.conf.local`",
)

ALLOWED_PHRASES = {
    "script/checkout_identity.sh": ("base rc6 moved it from `.setup.conf.local`",),
    "test/bats/smoke/checkout_identity_spec.bats": ('[ ! -e "${REPO}/.setup.conf.local" ]',),
    "test/bats/smoke/init_isaac_dirs_spec.bats": NEGATIVE_ASSERTIONS,
    "doc/test/TEST.md": NEGATIVE_ASSERTIONS,
    "src/doc/adr/0011-ci-architecture-with-self-hosted-gpu-runner.md": (
        "compose, `.setup.conf`, config, the base subtree",
    ),
    "src/doc/adr/0022-conform-bats-smoke-to-base-canonical-layout.md": (
        "+ `.setup.conf` relocation",
    ),
    "src/doc/adr/0025-output-mode-ros-or-python.md": (
        "key in `.setup.conf` `[environment]` (section-replaced by",
        "`.setup.conf.local`).",
        "UNVERIFIED; avoided by not defining the key in `.setup.conf`",
    ),
}


def is_excluded(path):
    name = Path(path).name
    return (path in EXCLUDED or path == ".base" or path.startswith(".base/")
            or name.startswith("CHANGELOG") or name in {".gitignore", ".dockerignore"})


def find_stale(files):
    hits = []
    for path, contents in files.items():
        if is_excluded(path):
            continue
        phrases = ALLOWED_PHRASES.get(path, ())
        for number, line in enumerate(contents.split("\n"), 1):
            remaining = line
            for phrase in phrases:
                remaining = remaining.replace(phrase, "", 1)
            if STALE.search(remaining):
                hits.append(f"{path}:{number}:{line}")
    return hits


class NotAGitCheckout(RuntimeError):
    """Git could not enumerate the tracked working-tree files."""


def tracked_files(root):
    """List nonempty tracked text files, respecting Git's binary attributes and symlinks."""
    try:
        result = subprocess.run(
            ["git", "grep", "-Ilz", "-e", "", "--", ".", ":!.base"],
            cwd=root, capture_output=True,
        )
    except OSError as exc:
        raise NotAGitCheckout(f"could not run git in {root}: {exc}") from exc
    if result.returncode not in (0, 1):
        raise NotAGitCheckout(f"git grep failed in {root}: {os.fsdecode(result.stderr).strip()}")
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[2],
                        help="Git checkout root (defaults to this script's checkout)")
    root = parser.parse_args(argv).root
    failed = False
    try:
        for path in tracked_files(root):
            if is_excluded(path):
                continue
            contents = (root / path).read_bytes().decode("utf-8", errors="surrogateescape")
            for hit in find_stale({path: contents}):
                print(hit)
                failed = True
    except (NotAGitCheckout, OSError) as exc:
        print(f"Stale naming scan failed: {exc}", file=sys.stderr)
        return 2
    if failed:
        return 1
    print("Stale naming scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
