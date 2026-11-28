"""Hosted checks for the standalone smoke script's case matrix."""

import re
import shlex
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "src/script/test/standalone_smoke.sh"


def _parse_cases(source: str) -> list[str]:
    """Returns the entries in the script's CASES array."""
    matrix = re.search(r"^CASES=\((.*?)^\s*\)", source, re.MULTILINE | re.DOTALL)
    assert matrix is not None, "Missing CASES array"
    return shlex.split(matrix.group(1), comments=True)


@pytest.mark.parametrize("token", ["needs-usd", "needs_usd", "USD_HOST"])
def test_script_has_no_usd_gate(token):
    assert token not in _SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("source", ["CASES=(\n)\n", "CASES=(\n  # No cases yet.\n)\n"])
def test_parse_empty_cases(source):
    assert _parse_cases(source) == []


def test_each_case_has_three_fields():
    source = _SCRIPT.read_text(encoding="utf-8")
    for entry in _parse_cases(source):
        assert len(entry.split("|")) == 3, (
            f"Expected basename|marker|timeout in {entry!r}"
        )


def test_script_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", _SCRIPT], check=True)


def test_empty_matrix_exits_from_outside_checkout(tmp_path):
    result = subprocess.run(
        ["bash", _SCRIPT], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert result.stdout == "No standalone smoke cases configured.\n"


@pytest.mark.parametrize("override", [False, True], ids=["defaults", "overrides"])
def test_configured_case_uses_checkout_and_container_paths(tmp_path, monkeypatch, override):
    checkout = tmp_path / "fresh checkout"
    runner = checkout / _SCRIPT.relative_to(_ROOT)
    runner.parent.mkdir(parents=True)
    source = _SCRIPT.read_text(encoding="utf-8")
    runner.write_text(source.replace("CASES=(\n", "CASES=(\n  'probe.py|READY|2'\n", 1))

    repo_dir = tmp_path / "alternate checkout" if override else checkout
    repo_dir.mkdir(exist_ok=True)
    (repo_dir / "justfile").touch()
    script_dir = "/mounted [scripts]" if override else "src/script"
    monkeypatch.delenv("ISAAC_SMOKE_REPO_DIR", raising=False)
    monkeypatch.delenv("ISAAC_SMOKE_SCRIPT_DIR", raising=False)
    if override:
        monkeypatch.setenv("ISAAC_SMOKE_REPO_DIR", str(repo_dir))
        monkeypatch.setenv("ISAAC_SMOKE_SCRIPT_DIR", script_dir)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    just = bin_dir / "just"
    just.write_text(
        "#!/bin/bash\n"
        "printf '%s\\0' \"$PWD\" \"$@\" >> \"$SMOKE_LOG\"\n"
        "case \"$*\" in\n"
        "  'docker exec -T -t stream true') exit 1 ;;\n"
        "  *'/isaac-sim/python.sh '*) echo READY ;;\n"
        "esac\n"
    )
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/bash\n[[ $1 != 1 ]] || /bin/sleep 0.1\n")
    for stub in (just, sleep):
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    log = tmp_path / "calls"
    monkeypatch.setenv("SMOKE_LOG", str(log))

    result = subprocess.run(
        ["bash", runner], cwd=tmp_path, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS probe.py" in result.stdout
    calls = log.read_text().rstrip("\0").split("\0")
    assert calls[:-1] == [
        str(repo_dir), "docker", "exec", "-T", "-t", "stream", "true",
        str(repo_dir), "docker", "run", "-t", "stream", "-d",
        str(repo_dir), "docker", "exec", "-T", "-t", "stream",
        "/isaac-sim/python.sh", f"{script_dir}/probe.py",
        str(repo_dir), "docker", "exec", "-T", "-t", "stream",
        "pkill", "-TERM", "-f", "--",
    ]
    pattern = calls[-1]
    assert re.search(pattern, f"/isaac-sim/kit/python/bin/python3 {script_dir}/probe.py")
    assert re.search(pattern, f"bash /isaac-sim/python.sh {script_dir}/probe.py")
    assert not re.search(pattern, f"/isaac-sim/kit/python/bin/python3 {script_dir}/probe.py.other")



def test_docker_lint_checks_standalone_smoke():
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY src/script/test/standalone_smoke.sh /lint/standalone_smoke.sh" in dockerfile
