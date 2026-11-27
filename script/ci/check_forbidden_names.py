#!/usr/bin/env python3
"""Check tracked text outside .base for names configured in FORBIDDEN_NAMES."""

import argparse
import os
import re
import sys
from pathlib import Path

from check_stale_naming import NotAGitCheckout, tracked_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--allow-unset", action="store_true")
    args = parser.parse_args()
    names = [item.strip() for item in os.environ.get("FORBIDDEN_NAMES", "").split(",") if item.strip()]
    if not names:
        if args.allow_unset:
            print("SKIPPED: FORBIDDEN_NAMES not set")
            return 0
        parser.error("FORBIDDEN_NAMES must contain at least one name")

    patterns = [re.compile(re.escape(name), re.IGNORECASE) for name in names]
    failed = False
    try:
        for path in tracked_files(args.root):
            label = path
            for pattern in patterns:
                label = pattern.sub("[redacted]", label)
            with (args.root / path).open(encoding="utf-8", errors="surrogateescape") as source:
                for number, line in enumerate(source, 1):
                    for index, pattern in enumerate(patterns, 1):
                        if pattern.search(line):
                            print(f"{label}:{number} (pattern {index})")
                            failed = True
    except (NotAGitCheckout, OSError):
        print("Could not scan Git working tree", file=sys.stderr)
        return 2
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
