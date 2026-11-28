"""Check the container permissions shipped in setup.toml (isaac#549)."""

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_SETUP = Path(__file__).resolve().parents[3] / "setup.toml"


@pytest.fixture(scope="module")
def setup():
    with _SETUP.open("rb") as config:
        return tomllib.load(config)


def test_privileged_mode_is_off(setup):
    assert setup.get("security", {}).get("privileged", False) is False


def test_device_bindings_exclude_the_host_dev_directory(setup):
    sources = {
        Path(binding["path"].split(":", 1)[0])
        for binding in setup.get("devices", {}).get("bindings", [])
    }
    assert Path("/dev") not in sources


@pytest.mark.parametrize("capability", ["SYS_ADMIN", "NET_ADMIN", "MKNOD"])
def test_capability_is_not_added(setup, capability):
    added = {
        entry["cap"].upper().removeprefix("CAP_")
        for entry in setup.get("security", {}).get("cap_add", [])
    }
    assert capability not in added


def test_seccomp_is_not_unconfined(setup):
    options = {entry["opt"] for entry in setup.get("security", {}).get("security_opt", [])}
    assert options.isdisjoint({"seccomp:unconfined", "seccomp=unconfined"}), options


def test_pid_namespace_is_not_host(setup):
    assert setup.get("network", {}).get("pid") != "host"


@pytest.mark.parametrize(
    "readme",
    ["README.md", "doc/README.zh-TW.md", "doc/README.zh-CN.md", "doc/README.ja.md"],
)
def test_readme_does_not_claim_host_pid_namespace(setup, readme):
    assert setup["network"]["pid"] == "private"
    assert "pid: host" not in (_SETUP.parent / readme).read_text(encoding="utf-8")


def test_ipc_namespace_is_not_host(setup):
    assert setup.get("network", {}).get("ipc") != "host"


def test_shared_memory_size_is_configured(setup):
    assert re.fullmatch(r"[1-9]\d*[mg]", setup["resources"]["shm_size"])


def test_network_mode_stays_host(setup):
    assert setup["network"]["mode"] == "host"
