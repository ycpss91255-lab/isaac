"""Host-side tests for the USD robot structure summary."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
from isaac_devkit import usd_model

pytestmark = pytest.mark.core


class TestPrimSummaryShape:
    def test_named_tuple_fields_match_adr(self):
        assert usd_model.PrimSummary._fields == (
            "prim_count",
            "joint_count",
            "link_paths",
            "root_prim",
            "usd_path",
        )


class TestSummarizePrimRecords:
    def test_folds_records_into_summary(self):
        records = [
            ("/bot", "Xform"),
            ("/bot/base_link", "Xform"),
            ("/bot/wheel", "Xform"),
            ("/bot/base_link/j1", "PhysicsRevoluteJoint"),
        ]
        summary = usd_model._summarize_prim_records(records, "/out.usd")
        assert summary.root_prim == "/bot"
        assert summary.prim_count == 4
        assert summary.joint_count == 1
        assert summary.link_paths == ["/bot/base_link", "/bot/wheel"]
        assert summary.usd_path == "/out.usd"

    def test_empty_records_raise(self):
        with pytest.raises(ValueError, match="no prims"):
            usd_model._summarize_prim_records([], "/out.usd")
