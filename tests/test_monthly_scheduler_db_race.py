from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_UTILS = _PROJECT_ROOT / "src" / "utils"
if str(_UTILS) not in sys.path:
    sys.path.insert(0, str(_UTILS))

import init_db  # noqa: E402

_GUARD_SPEC = importlib.util.spec_from_file_location(
    "cache_depletion_guard",
    _PROJECT_ROOT / "tools" / "cache_depletion_guard.py",
)
assert _GUARD_SPEC is not None
assert _GUARD_SPEC.loader is not None
cache_depletion_guard = importlib.util.module_from_spec(_GUARD_SPEC)
_GUARD_SPEC.loader.exec_module(cache_depletion_guard)


def test_monthly_quantum_schedules_use_host_mapping_utc_times() -> None:
    policy = json.loads(
        (_PROJECT_ROOT / "src" / "config" / "execution_policy.json").read_text(
            encoding="utf-8"
        )
    )

    assert policy["timezone"] == "UTC"
    assert policy["schedules"]["quantum_cache_fill_monthly"]["hour"] == 7
    assert policy["schedules"]["shors_monthly_benchmark"]["hour"] == 8


def test_get_connection_sets_bounded_busy_timeout(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")

    connection = init_db.get_connection()
    try:
        timeout_ms = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        connection.close()

    assert 0 < timeout_ms <= 10_000


class _TrackingConnection:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, sql: str, parameters=()):
        if sql.lstrip().startswith("SELECT 1"):
            return _EmptyResult()
        return _WriteResult()

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _EmptyResult:
    def fetchone(self):
        return None


class _WriteResult:
    pass


def test_run_guard_closes_db_before_spawning_early_fill(tmp_path, monkeypatch) -> None:
    live_dir = tmp_path / "liveCache"
    live_dir.mkdir()
    (live_dir / "ty_string_cache_capacity.txt").write_text("100", encoding="utf-8")
    (live_dir / "ty_string_cache.txt").write_text("0\n", encoding="utf-8")
    connection = _TrackingConnection()
    observed_closed_state: list[bool] = []

    monkeypatch.setattr(cache_depletion_guard, "_CAPACITY_FILE", live_dir / "ty_string_cache_capacity.txt")
    monkeypatch.setattr(cache_depletion_guard, "_LIVE_CACHE", live_dir / "ty_string_cache.txt")
    monkeypatch.setattr(cache_depletion_guard.init_db, "init_db", lambda: None)
    monkeypatch.setattr(cache_depletion_guard.init_db, "get_connection", lambda: connection)
    monkeypatch.setattr(cache_depletion_guard, "_load_threshold", lambda: 0.25)

    def fake_run(*_args, **_kwargs) -> None:
        observed_closed_state.append(connection.closed)

    monkeypatch.setattr(cache_depletion_guard.subprocess, "run", fake_run)

    cache_depletion_guard.run_guard()

    assert observed_closed_state == [True]
    assert connection.closed