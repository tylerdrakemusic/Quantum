"""
Regression test for BFX-20260603-drain-curve-stale

Verifies that _load_cache_widget_data returns sparkline_points sorted by
timestamp even when the cache_usage.jsonl entries are written out of order.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DASHBOARD_PATH = _REPO_ROOT / "tools" / "gen_benchmark_dashboard.py"


def _load_dashboard():
    """Import gen_benchmark_dashboard fresh (avoids DB side-effects at module level)."""
    spec = importlib.util.spec_from_file_location("gen_benchmark_dashboard", _DASHBOARD_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestDrainCurveOrdering:
    """sparkline_points must be sorted by timestamp regardless of JSONL write order."""

    def test_out_of_order_entries_are_sorted(self, tmp_path: Path) -> None:
        """Out-of-order cache_usage.jsonl entries produce a time-sorted drain curve."""
        # _load_cache_widget_data builds: _ROOT / "src" / "data" / "cache_usage.jsonl"
        data_dir = tmp_path / "src" / "data"
        data_dir.mkdir(parents=True)
        jsonl = data_dir / "cache_usage.jsonl"
        # Write entries deliberately out of chronological order
        entries = [
            {"ts": "2026-06-03T12:00:00Z", "remaining": 800_000},
            {"ts": "2026-06-01T08:00:00Z", "remaining": 1_000_000},
            {"ts": "2026-06-02T16:00:00Z", "remaining": 900_000},
        ]
        jsonl.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )

        mod = _load_dashboard()

        with patch.object(mod, "_ROOT", tmp_path):
            data = mod._load_cache_widget_data()

        pts = data["sparkline_points"]
        assert len(pts) == 3
        timestamps = [ts for ts, _ in pts]
        assert timestamps == sorted(timestamps), (
            f"sparkline_points not sorted by timestamp: {timestamps}"
        )
        # Verify correct chronological order
        assert timestamps[0] == "2026-06-01T08:00:00Z"
        assert timestamps[1] == "2026-06-02T16:00:00Z"
        assert timestamps[2] == "2026-06-03T12:00:00Z"

    def test_already_ordered_entries_unchanged(self, tmp_path: Path) -> None:
        """In-order entries are returned unchanged."""
        data_dir = tmp_path / "src" / "data"
        data_dir.mkdir(parents=True)
        jsonl = data_dir / "cache_usage.jsonl"
        entries = [
            {"ts": "2026-06-01T00:00:00Z", "remaining": 1_000_000},
            {"ts": "2026-06-02T00:00:00Z", "remaining": 750_000},
            {"ts": "2026-06-03T00:00:00Z", "remaining": 500_000},
        ]
        jsonl.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )

        mod = _load_dashboard()

        with patch.object(mod, "_ROOT", tmp_path):
            data = mod._load_cache_widget_data()

        pts = data["sparkline_points"]
        assert len(pts) == 3
        timestamps = [ts for ts, _ in pts]
        assert timestamps == sorted(timestamps)

    def test_single_entry_does_not_crash(self, tmp_path: Path) -> None:
        """A single JSONL entry produces a one-element list without error."""
        data_dir = tmp_path / "src" / "data"
        data_dir.mkdir(parents=True)
        jsonl = data_dir / "cache_usage.jsonl"
        jsonl.write_text(
            json.dumps({"ts": "2026-06-01T00:00:00Z", "remaining": 500_000}) + "\n",
            encoding="utf-8",
        )

        mod = _load_dashboard()

        with patch.object(mod, "_ROOT", tmp_path):
            data = mod._load_cache_widget_data()

        assert len(data["sparkline_points"]) == 1

    def test_empty_jsonl_produces_empty_sparkline(self, tmp_path: Path) -> None:
        """An empty (or absent) JSONL produces an empty sparkline_points list."""
        mod = _load_dashboard()

        # No cache_usage.jsonl written — _ROOT points at tmp_path which lacks it
        with patch.object(mod, "_ROOT", tmp_path):
            data = mod._load_cache_widget_data()

        assert data["sparkline_points"] == []
