#!/usr/bin/env python3
"""Check that recursive Dockerfile ownership changes stay under HOME."""

import argparse
from collections.abc import Iterator
import json
from pathlib import Path
import re
import shlex


# Quoted and escaped separators belong to the command, e.g. find -exec ... \;.
_SHELL_SYNTAX = re.compile(
    r"""'[^']*'|"(?:\\.|[^"\\])*"|\\.|(?P<separator>&&|\|\||[;&|()])"""
)
_RECURSIVE_FLAG = re.compile(r"-[a-zA-Z]*R[a-zA-Z]*")
_INSTRUCTION = re.compile(r"^\s*(?:ONBUILD\s+)?(?:RUN|CMD|ENTRYPOINT)\s+", re.I)
_PREFIXES = {"if", "then", "else", "do", "sudo", "exec", "command"}


def _commands(line: str) -> Iterator[tuple[str, str]]:
    """Yields each shell command with its preceding control operator."""
    start = 0
    separator = ""
    for match in _SHELL_SYNTAX.finditer(line):
        if match.lastgroup == "separator":
            yield separator, line[start:match.start()].strip()
            separator = match.group()
            start = match.end()
    yield separator, line[start:].strip()


def _under_home(path: str) -> bool:
    """Returns whether a literal target names a path under HOME."""
    return path.startswith(("${HOME}/", "$HOME/")) and ".." not in path.split("/")


def _unsafe_chown(args: list[str], from_find: bool = False) -> bool:
    """Checks recursive flags and file operands, including options after files."""
    recursive = False
    reference = False
    operands = []
    options = True
    for arg in args:
        if options and arg == "--":
            options = False
        elif options and arg.startswith("-") and arg != "-":
            recursive |= (
                arg == "--recursive" or bool(_RECURSIVE_FLAG.fullmatch(arg))
            )
            reference |= arg.startswith("--reference=")
        else:
            operands.append(arg)
    targets = operands if reference else operands[1:]
    if not recursive:
        return False
    if not targets:
        return not from_find
    return any(
        not _under_home(path) and not (from_find and path == "{}")
        for path in targets
    )


def _find_under_home(args: list[str]) -> bool:
    """Checks every find starting point before the search expression."""
    roots = []
    for arg in args:
        if not roots and arg in {"-H", "-L", "-P", "--"}:
            continue
        if arg.startswith("-") or arg in {"!", "("}:
            break
        roots.append(arg)
    return bool(roots) and all(map(_under_home, roots))


def _unsafe_find_exec(args: list[str], under_home: bool) -> bool:
    """Checks chown invocations embedded in a find expression."""
    for i, arg in enumerate(args[:-1]):
        if arg not in {"-exec", "-execdir"} or Path(args[i + 1]).name != "chown":
            continue
        chown_args = []
        for word in args[i + 2:]:
            if word in {"+", ";"}:
                break
            chown_args.append(word)
        if not under_home or _unsafe_chown(chown_args, from_find=True):
            return True
    return False


def _invocations(shell: str) -> Iterator[tuple[str, str, list[str]]]:
    """Yields the operator, source text, and argv for each invocation."""
    if shell.startswith("["):
        try:
            words = json.loads(shell)
        except json.JSONDecodeError:
            pass  # A shell-form instruction can start with the test command [.
        else:
            if isinstance(words, list) and all(isinstance(w, str) for w in words):
                yield "", shell, words
                return
    for separator, command in _commands(shell):
        words = shlex.split(command)
        while words and (
            words[0] in _PREFIXES or re.match(r"(?:\w+=|--mount=)", words[0])
        ):
            words.pop(0)
        if words:
            yield separator, command, words


def violations(dockerfile_text: str) -> list[str]:
    """Returns commands that can recursively chown paths outside HOME.

    Args:
        dockerfile_text: Contents of the Dockerfile to check.

    Returns:
        Offending commands in source order, with line continuations joined.
    """
    lines = (
        line for line in dockerfile_text.splitlines()
        if not line.lstrip().startswith("#")
    )
    logical_lines = "\n".join(lines).replace("\\\n", "").splitlines()
    errors = []
    for line in logical_lines:
        if "chown" not in line:
            continue
        shell = _INSTRUCTION.sub("", line)
        safe_find = False
        previous_command = ""
        for separator, command, words in _invocations(shell):
            if not words:
                continue
            name, args = Path(words[0]).name, words[1:]
            piped_from_home = separator == "|" and safe_find
            safe_find = name == "find" and _find_under_home(args)
            if name == "chown" and _unsafe_chown(args):
                errors.append(command)
            elif name == "find" and _unsafe_find_exec(args, safe_find):
                errors.append(command)
            elif name == "xargs":
                for i, arg in enumerate(args):
                    if Path(arg).name == "chown":
                        if not piped_from_home or _unsafe_chown(
                            args[i + 1:], from_find=True
                        ):
                            if separator == "|":
                                command = f"{previous_command} | {command}"
                            errors.append(command)
                        break
            previous_command = command
    return errors


def main() -> int:
    """Prints offending commands and returns a nonzero status if any are found."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dockerfile", nargs="?", type=Path, default=Path("Dockerfile"))
    errors = violations(parser.parse_args().dockerfile.read_text(encoding="utf-8"))
    for command in errors:
        print(command)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
