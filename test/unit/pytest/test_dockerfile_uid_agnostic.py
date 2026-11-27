"""Host identity, importer permissions, and CI contracts for the Isaac bases (#474)."""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILE = (_ROOT / "Dockerfile").read_text()
# Drop Dockerfile comments before joining continued shell commands.
_ACTIVE = "\n".join(
    line for line in _DOCKERFILE.splitlines() if not line.lstrip().startswith("#")
).replace("\\\n", " ")
_STAGES = re.findall(r"(?ims)^FROM[ \t]+([^\n]+)\n(.*?)(?=^FROM\s|\Z)", _ACTIVE)
_SYS = next(body for header, body in _STAGES if re.search(r"\sAS\s+sys\s*$", header, re.I))


def test_dockerfile_has_no_literal_official_uid():
    assert "1234" not in _DOCKERFILE


def test_account_commands_do_not_name_the_isaac_sim_group():
    commands = re.findall(r"\b(?:usermod|groupadd)\s+([^;&\n]+)", _ACTIVE)
    for command in commands:
        assert not re.search(r"(?<![\w/-])isaac-sim(?![\w/-])", command), command


def test_sys_consumes_ids_probed_as_the_base_image_user():
    # A COPY mode for the probe files also applies to the directory it creates.
    for copy in re.findall(r"(?im)^COPY[ \t]+(.+)$", _SYS):
        args = shlex.split(copy)
        if args[-1].rstrip("/") == "/etc/isaac" and "/tmp/base-gid" in args:
            assert not any(arg.startswith("--chmod=") for arg in args), copy

    for index, (header, body) in enumerate(_STAGES):
        source = re.fullmatch(r"\$(?:{BASE_IMAGE}|BASE_IMAGE)\s+AS\s+(\S+)", header.strip(), re.I)
        if not source:
            continue
        inherited_user = re.split(r"(?im)^USER\s", body, maxsplit=1)[0]
        runs = "\n".join(re.findall(r"(?im)^RUN\s+(.+)$", inherited_user))
        if all(re.search(rf"\bid\s+-{flag}\b", runs) for flag in ("u", "g")):
            name = re.escape(source[1])
            if re.search(rf"(?:--from=|\bfrom=)(?:{name}|{index})(?=[,\s])", _SYS):
                return
            if any(re.fullmatch(rf"{name}\s+AS\s+sys", h, re.I) for h, _ in _STAGES):
                return
    pytest.fail("sys must consume the UID and GID captured under the base image's USER")


def test_sudoers_grants_passwordless_sudo_by_host_uid():
    assert re.search(r"#\${USER_UID}\s+ALL=\(ALL\)\s+NOPASSWD:\s*ALL[^\n]*"
                     r"/etc/sudoers\b", _SYS)


def test_host_user_joins_the_group_resolved_from_the_official_gid():
    # Permit either the numeric GID itself or a group looked up by that GID.
    joins = re.findall(r"\b(?:usermod|useradd)\s+[^;&\n]*?"
                       r"(?:-[a-zA-Z]*G\s+|--groups[= ])([^;&\n]+?)\s+[\"']?\${?USER_NAME\b",
                       _SYS)
    assignments = dict(re.findall(r"\b(\w+)=([^;&\n]+)", _SYS))
    for group in joins:
        # Follow assignments such as group=$(getent group "$gid" | cut ...)
        # and gid=$(cat /path/copied/from/base) without prescribing their names.
        pending = [group]
        seen = set()
        while pending:
            value = pending.pop()
            if re.search(r"\$\(\s*(?:cat\s|<)", value):
                return
            for var in re.findall(r"\$\{?(\w+)", value):
                if var in seen or var in {"USER_GID", "HOST_GID"}:
                    continue
                seen.add(var)
                if var in assignments:
                    pending.append(assignments[var])
                # Probe files can also be sourced, or consumed by shell read.
                elif "gid" in var.lower() and re.search(r"(?:^|\s)(?:source|\.|read)\s", _SYS):
                    return
    pytest.fail("expected a supplementary group derived from the base GID for USER_NAME")


def test_mjcf_group_write_rule_is_nonrecursive_and_inherited_by_both_targets():
    stages = [body for header, body in _STAGES if header.split()[-1] in {"sys", "devel-base"}]
    runs = [cmd for stage in stages for cmd in re.findall(r"(?im)^RUN\s+(.+)$", stage)
            if "isaacsim.asset.importer.mjcf" in cmd and "/data" in cmd]
    write_rules = []
    for cmd in runs:
        for args in re.findall(r"\bchmod\s+([^;&|]+)", cmd):
            words = shlex.split(args)
            assert not any(w == "--recursive" or re.fullmatch(r"-[A-Za-z]*R[A-Za-z]*", w)
                           for w in words), args
            operands = [word for word in words if not word.startswith("-")]
            mode, *targets = operands
            assert all(t.rstrip("/") not in {"/isaac-sim", "/isaac-sim/exts", "/isaac-sim/exts/*"}
                       for t in targets), args
            if re.fullmatch(r"[0-7]{3,4}", mode):
                group_write = (int(mode, 8) & 0o022) == 0o020
            else:
                group_write = re.fullmatch(r"g[+=][rwxX]*w[rwxX]*", mode)
            if group_write:
                write_rules.append(cmd)
    assert write_rules, "both matrix targets must inherit group write on the MJCF data directories"
    assert any(re.search(r"isaacsim\.asset\.importer\.mjcf(?:\.ui|\*|\{[^}]*\.ui)", rule)
               for rule in write_rules), "include the UI extension's data directory"
    # The default import writes next to nv_ant.xml, one directory below data.
    assert any("/mjcf" in rule for rule in write_rules), "include the existing data/mjcf directory"


def test_uid_setup_preserves_the_official_tree_ownership():
    subprocess.run([sys.executable, _ROOT / "script/ci/check_no_recursive_chown.py",
                    _ROOT / "Dockerfile"], check=True)


_JOBS = yaml.safe_load((_ROOT / ".github/workflows/main.yaml").read_text())["jobs"]


def _matrix_args(script):
    for line in script.replace("\\\n", " ").splitlines():
        match = re.match(r'\s*(?:\w+=\S+\s+)*(?:bash\s+)?"?(?:\./|\$\{?repo_root\}?/)?'
                         r'script/ci/uid_matrix\.sh"?'
                         r"(?=\s|$)(.*)", line)
        if match:
            yield shlex.split(match[1], comments=True)


def test_core_unit_runs_uid_matrix_without_a_gpu():
    assert any("--no-gpu" in args and "--dry-run" not in args
               for step in _JOBS["core-unit"]["steps"] if not step.get("continue-on-error")
               for args in _matrix_args(step.get("run", "")))


def test_core_gpu_runs_uid_matrix_with_a_gpu():
    job = _JOBS["core-gpu"]
    assert "/gpu-self-hosted.yml@" in job["uses"]
    script = _ROOT / job["with"]["run-script"]
    assert any(not args for args in _matrix_args(script.read_text())), (
        f"{script.name} must invoke the GPU UID matrix"
    )
