"""Offline characterization of the official Isaac Sim image inventory."""

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_SCRIPT = Path(__file__).resolve().parents[3] / "script/ci/track_isaac_sim.py"
_TESTS = "isaac-sim/tests/"
_CONFIG = _TESTS + "test_config.json"
_RUNNER = "isaac-sim/run_tests.py"
_SUITES = b'{"suites":[{"name":"smoke","include":["tests-*.sh"],"default_bucket":"default"}]}'
_RUNNER_CONTENT = b"# test runner\n"


@pytest.fixture(scope="module")
def tracker():
    spec = importlib.util.spec_from_file_location("track_isaac_sim_inventory", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _RegistryResponse(io.BytesIO):
    """Serve a fresh readable stream for a JSON document or a layer blob."""

    def __init__(self, payload):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload).encode("utf-8")
        super().__init__(payload)


@pytest.fixture
def registry(tracker, monkeypatch):
    responses = {}

    def get(path, token):
        assert path in responses, f"Unexpected registry request: {path}"
        return _RegistryResponse(responses[path])

    monkeypatch.setattr(tracker, "registry_get", get)
    return responses


def _tar(entries):
    """Pack path-to-bytes entries into a layer, using None for a directory."""
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode="w") as archive:
        for path, content in entries.items():
            entry = tarfile.TarInfo(path)
            if content is None:
                entry.type = tarfile.DIRTYPE
                archive.addfile(entry)
            else:
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
    return blob.getvalue()


@pytest.fixture
def add_image(tracker, monkeypatch, registry):
    layers = {}
    monkeypatch.setattr(tracker, "image_layers", lambda version, token: layers[version])

    def add(version, *blobs):
        layers[version] = []
        for blob in blobs:
            digest = "sha256:" + hashlib.sha256(blob).hexdigest()
            registry["blobs/" + digest] = blob
            layers[version].append((digest, ""))

    return add


def test_read_layer_collects_metadata_scripts_and_root_directory(tracker):
    script = _TESTS + "tests-smoke.sh"
    blob = _tar({
        "isaac-sim": None,
        _CONFIG: _SUITES,
        _RUNNER: _RUNNER_CONTENT,
        script: b"exit 0\n",
        _TESTS + "setup.sh": b"",
        _TESTS + "nested/tests-other.sh": b"",
    })
    files, hidden, created_root = tracker.read_layer(io.BytesIO(blob))
    assert files == {_CONFIG: _SUITES, _RUNNER: _RUNNER_CONTENT, script: None}
    assert hidden == set()
    assert created_root is True


@pytest.mark.parametrize("path", [_CONFIG, _RUNNER])
def test_read_layer_rejects_oversize_metadata(tracker, path):
    blob = _tar({path: b"x" * (2 * 1024 * 1024 + 1)})
    with pytest.raises(ValueError, match="Unsupported test metadata"):
        tracker.read_layer(io.BytesIO(blob))


@pytest.mark.parametrize(
    ("whiteout", "expected"),
    [
        (".wh.tests-old.sh", {"tests-kept.sh", "tests-new.sh"}),
        (".wh..wh..opq", {"tests-new.sh"}),
    ],
    ids=["single-script", "opaque-directory"],
)
def test_image_inventory_applies_whiteouts_to_older_scripts(tracker, add_image, whiteout, expected):
    base = _tar({
        _RUNNER: _RUNNER_CONTENT,
        _TESTS + "tests-old.sh": b"",
        _TESTS + "tests-kept.sh": b"",
    })
    patch = _tar({_CONFIG: _SUITES, _TESTS + whiteout: b"", _TESTS + "tests-new.sh": b""})
    add_image("6.2.0", base, patch)

    inventory, runner_digest = tracker.image_inventory("6.2.0", "token", {})
    assert inventory == {"smoke": expected}
    assert runner_digest == hashlib.sha256(_RUNNER_CONTENT).digest()


@pytest.mark.parametrize(
    ("history", "expected_steps"),
    [
        ([{"created_by": "install"}, {"empty_layer": True}, {"created_by": "patch"}],
         ["install", "patch"]),
        ([{"created_by": "unmatched"}], ["", ""]),
    ],
    ids=["aligned-history", "mismatched-history"],
)
def test_image_layers_resolves_linux_amd64_index_and_history(
    tracker, registry, history, expected_steps
):
    manifest, config, base, patch, windows, arm = ["sha256:" + char * 64 for char in "abcdef"]
    registry["manifests/6.2.0"] = {
        "manifests": [
            {"digest": windows, "platform": {"os": "windows", "architecture": "amd64"}},
            {"digest": arm, "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": manifest, "platform": {"os": "linux", "architecture": "amd64"}},
        ],
    }
    registry["manifests/" + manifest] = {
        "config": {"digest": config},
        "layers": [{"digest": base}, {"digest": patch}],
    }
    registry["blobs/" + config] = {"history": history}

    assert tracker.image_layers("6.2.0", "token") == [
        (base, expected_steps[0]),
        (patch, expected_steps[1]),
    ]


def test_inventory_diff_returns_unavailable_for_missing_scripts(tracker, add_image):
    metadata = {_CONFIG: _SUITES, _RUNNER: _RUNNER_CONTENT}
    add_image("6.2.0", _tar({**metadata, _TESTS + "tests-old.sh": b""}))
    add_image("6.2.1", _tar(metadata))

    with pytest.raises(ValueError, match="Missing test scripts"):
        tracker.image_inventory("6.2.1", "token", {})
    assert tracker.inventory_diff("6.2.0", "6.2.1", "token") == (None, False)


@pytest.mark.parametrize(
    ("new_runner", "runner_changed"),
    [(_RUNNER_CONTENT, False), (b"# updated test runner\n", True)],
    ids=["same-runner", "changed-runner"],
)
def test_inventory_diff_reports_script_and_runner_changes(
    tracker, add_image, new_runner, runner_changed
):
    old = _tar({_CONFIG: _SUITES, _RUNNER: _RUNNER_CONTENT, _TESTS + "tests-old.sh": b""})
    new = _tar({_CONFIG: _SUITES, _RUNNER: new_runner, _TESTS + "tests-new.sh": b""})
    add_image("6.2.0", old)
    add_image("6.2.1", new)

    diff = {
        "added": {"smoke": ["tests-new.sh"]},
        "removed": {"smoke": ["tests-old.sh"]},
        "renamed": {},
    }
    assert tracker.inventory_diff("6.2.0", "6.2.1", "token") == (diff, runner_changed)
