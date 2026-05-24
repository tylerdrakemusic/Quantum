"""
Unit tests for tools/cache_depletion_guard.py

Covers:
  - check_ok path (pct_full >= threshold)
  - depletion_detected + fill_triggered path (pct_full < threshold, no cooldown)
  - fill_skipped_cooldown path (pct_full < threshold, already filled this month)
  - Missing capacity baseline file (graceful exit, no crash)
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root and src/utils are on sys.path
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# We import the guard module by path so tests are independent of install state
_GUARD_MODULE_PATH = _REPO_ROOT / "tools" / "cache_depletion_guard.py"


def _load_guard():
    """Import cache_depletion_guard fresh for each test."""
    spec = importlib.util.spec_from_file_location(
        "cache_depletion_guard", _GUARD_MODULE_PATH
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    """Return a temp directory playing the role of src/data/liveCache/."""
    d = tmp_path / "liveCache"
    d.mkdir()
    return d


def _write_cache(cache_dir: Path, bits: int) -> Path:
    """Write a fake cache file with `bits` '1' characters."""
    p = cache_dir / "ty_string_cache.txt"
    # Write in lines of 1000 bits to mimic real format
    lines = []
    remaining = bits
    while remaining > 0:
        chunk = min(1000, remaining)
        lines.append("1" * chunk)
        remaining -= chunk
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _write_capacity(cache_dir: Path, capacity_bytes: int) -> Path:
    """Write a fake capacity baseline file."""
    p = cache_dir / "ty_string_cache_capacity.txt"
    p.write_text(f"{capacity_bytes}\n", encoding="utf-8")
    return p


def _make_mock_conn(has_fill_triggered_this_month: bool) -> MagicMock:
    """Return a mock DB connection whose cooldown query returns accordingly."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,) if has_fill_triggered_this_month else None
    conn.execute.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckOk:
    """pct_full >= threshold → action = check_ok, no fill triggered."""

    def test_check_ok_logs_and_exits_zero(self, cache_dir: Path) -> None:
        capacity = 10_000
        # 80% full — well above 25% threshold
        current_bits = 8_000
        _write_capacity(cache_dir, capacity)
        _write_cache(cache_dir, current_bits)

        guard = _load_guard()

        mock_conn = _make_mock_conn(has_fill_triggered_this_month=False)
        logged_actions: list[str] = []

        def fake_log_health(conn, bits_remaining, capacity_bits, pct_full, action_taken):
            logged_actions.append(action_taken)

        with (
            patch.object(guard, "_LIVE_CACHE", cache_dir / "ty_string_cache.txt"),
            patch.object(guard, "_CAPACITY_FILE", cache_dir / "ty_string_cache_capacity.txt"),
            patch.object(guard, "_log_health", side_effect=fake_log_health),
            patch.object(guard.init_db, "init_db"),
            patch.object(guard.init_db, "get_connection", return_value=mock_conn),
            patch.object(guard, "_load_threshold", return_value=0.25),
        ):
            guard.run_guard()   # must not raise

        assert "check_ok" in logged_actions
        assert "fill_triggered" not in logged_actions
        assert "depletion_detected" not in logged_actions


class TestFillTriggered:
    """pct_full < threshold, no cooldown → depletion_detected + fill_triggered."""

    def test_fill_triggered_calls_subprocess(self, cache_dir: Path) -> None:
        capacity = 10_000
        # 10% full — below 25% threshold
        current_bits = 1_000
        _write_capacity(cache_dir, capacity)
        _write_cache(cache_dir, current_bits)

        guard = _load_guard()

        mock_conn = _make_mock_conn(has_fill_triggered_this_month=False)
        logged_actions: list[str] = []

        def fake_log_health(conn, bits_remaining, capacity_bits, pct_full, action_taken):
            logged_actions.append(action_taken)

        with (
            patch.object(guard, "_LIVE_CACHE", cache_dir / "ty_string_cache.txt"),
            patch.object(guard, "_CAPACITY_FILE", cache_dir / "ty_string_cache_capacity.txt"),
            patch.object(guard, "_log_health", side_effect=fake_log_health),
            patch.object(guard.init_db, "init_db"),
            patch.object(guard.init_db, "get_connection", return_value=mock_conn),
            patch.object(guard, "_load_threshold", return_value=0.25),
            patch.object(guard, "_cooldown_active", return_value=False),
            patch("subprocess.run") as mock_subprocess,
        ):
            guard.run_guard()

        assert "depletion_detected" in logged_actions
        assert "fill_triggered" in logged_actions
        mock_subprocess.assert_called_once()
        # Verify fill_cache.py is what gets called
        call_args = mock_subprocess.call_args[0][0]
        assert "fill_cache.py" in str(call_args[-1])

    def test_fill_triggered_order(self, cache_dir: Path) -> None:
        """depletion_detected must be logged before fill_triggered."""
        capacity = 10_000
        current_bits = 500
        _write_capacity(cache_dir, capacity)
        _write_cache(cache_dir, current_bits)

        guard = _load_guard()

        mock_conn = _make_mock_conn(has_fill_triggered_this_month=False)
        logged_actions: list[str] = []

        def fake_log_health(conn, bits_remaining, capacity_bits, pct_full, action_taken):
            logged_actions.append(action_taken)

        with (
            patch.object(guard, "_LIVE_CACHE", cache_dir / "ty_string_cache.txt"),
            patch.object(guard, "_CAPACITY_FILE", cache_dir / "ty_string_cache_capacity.txt"),
            patch.object(guard, "_log_health", side_effect=fake_log_health),
            patch.object(guard.init_db, "init_db"),
            patch.object(guard.init_db, "get_connection", return_value=mock_conn),
            patch.object(guard, "_load_threshold", return_value=0.25),
            patch.object(guard, "_cooldown_active", return_value=False),
            patch("subprocess.run"),
        ):
            guard.run_guard()

        depletion_idx = logged_actions.index("depletion_detected")
        fill_idx = logged_actions.index("fill_triggered")
        assert depletion_idx < fill_idx


class TestFillSkippedCooldown:
    """pct_full < threshold, cooldown active → fill_skipped_cooldown, no subprocess."""

    def test_skipped_when_cooldown_active(self, cache_dir: Path) -> None:
        capacity = 10_000
        current_bits = 1_000
        _write_capacity(cache_dir, capacity)
        _write_cache(cache_dir, current_bits)

        guard = _load_guard()

        mock_conn = _make_mock_conn(has_fill_triggered_this_month=True)
        logged_actions: list[str] = []

        def fake_log_health(conn, bits_remaining, capacity_bits, pct_full, action_taken):
            logged_actions.append(action_taken)

        with (
            patch.object(guard, "_LIVE_CACHE", cache_dir / "ty_string_cache.txt"),
            patch.object(guard, "_CAPACITY_FILE", cache_dir / "ty_string_cache_capacity.txt"),
            patch.object(guard, "_log_health", side_effect=fake_log_health),
            patch.object(guard.init_db, "init_db"),
            patch.object(guard.init_db, "get_connection", return_value=mock_conn),
            patch.object(guard, "_load_threshold", return_value=0.25),
            patch.object(guard, "_cooldown_active", return_value=True),
            patch("subprocess.run") as mock_subprocess,
        ):
            guard.run_guard()

        assert "fill_skipped_cooldown" in logged_actions
        assert "fill_triggered" not in logged_actions
        mock_subprocess.assert_not_called()


class TestMissingCapacityBaseline:
    """Missing capacity baseline → exit 1, no crash, error logged to stderr."""

    def test_exits_nonzero_when_baseline_missing(
        self, cache_dir: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # Do NOT write the capacity file
        _write_cache(cache_dir, 5_000)

        guard = _load_guard()

        with (
            patch.object(guard, "_LIVE_CACHE", cache_dir / "ty_string_cache.txt"),
            patch.object(guard, "_CAPACITY_FILE", cache_dir / "ty_string_cache_capacity.txt"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                guard.run_guard()

        assert exc_info.value.code == 1

    def test_main_exits_nonzero_when_baseline_missing(self, cache_dir: Path) -> None:
        _write_cache(cache_dir, 5_000)

        guard = _load_guard()

        with (
            patch.object(guard, "_LIVE_CACHE", cache_dir / "ty_string_cache.txt"),
            patch.object(guard, "_CAPACITY_FILE", cache_dir / "ty_string_cache_capacity.txt"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                guard.main()

        assert exc_info.value.code == 1
