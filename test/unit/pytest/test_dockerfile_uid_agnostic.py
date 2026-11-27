"""Host identity and no-GPU CI contracts for the two Isaac base images (#474)."""

import re
import shlex
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


def test_recursive_chown_targets_only_children_of_home():
    for command in re.findall(r"\bchown\s+([^;&|<>\n]+)", _ACTIVE):
        args = shlex.split(command)
        if not any(a == "--recursive" or re.fullmatch(r"-[a-zA-Z]*R[a-zA-Z]*", a)
                   for a in args):
            continue
        operands = [a for a in args if not a.startswith("-")]
        # --reference supplies the owner in place of the usual first operand.
        targets = operands if any(a.startswith("--reference=") for a in args) else operands[1:]
        assert targets, command
        for path in targets:
            assert path.startswith(("${HOME}/", "$HOME/")) and ".." not in path.split("/"), command


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


def _ci_steps(workflow="main.yaml"):
    workflows = _ROOT / ".github" / "workflows"
    for job in yaml.safe_load((workflows / workflow).read_text())["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step and not step.get("continue-on-error"):
                yield "\n".join(line for line in step["run"].splitlines()
                                if not line.lstrip().startswith("#")).replace("\\\n", " ")
        reusable = job.get("uses", "")
        if reusable.startswith("./.github/workflows/"):
            yield from _ci_steps(Path(reusable).name)


def test_ci_runs_uid_matrix_without_a_gpu():
    for step in _ci_steps():
        for command in step.splitlines():
            if re.search(r"(?:^\s*|&&\s*)(?:BASE_IMAGE=\S+\s+)?"
                         r"(?:bash\s+)?(?:\./)?script/ci/uid_matrix\.sh\s",
                         command):
                args = shlex.split(command, comments=True)
                if "--no-gpu" in args and "--dry-run" not in args:
                    return
    pytest.fail("expected a CI run step invoking script/ci/uid_matrix.sh --no-gpu")


def test_ci_rejects_recursive_chown_in_the_dockerfile():
    for step in _ci_steps():
        if not re.search(r"\bgrep\b[^\n]*chown[^\n]*(?:R|recursive)[^\n]*Dockerfile\b", step):
            continue
        if re.search(r"!\s*grep\b", step) or re.search(r"\b(?:exit [1-9]\d*|false)\b", step):
            return
    pytest.fail("expected a CI grep step that fails on forbidden recursive chown")
