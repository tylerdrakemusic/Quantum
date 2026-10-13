from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_bdd import given, scenarios, then, when

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "utils"))

import init_db  # noqa: E402
import execution_policy  # noqa: E402
import run_vqe_bench as rvb  # noqa: E402

dashboard_spec = importlib.util.spec_from_file_location(
    "vqe_terminal_evidence_dashboard",
    PROJECT_ROOT / "tools" / "gen_benchmark_dashboard.py",
)
assert dashboard_spec is not None
dashboard = importlib.util.module_from_spec(dashboard_spec)
assert dashboard_spec.loader is not None
dashboard_spec.loader.exec_module(dashboard)  # type: ignore[union-attr]

scenarios("vqe_terminal_evidence.feature")


@pytest.fixture
def vqe_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    conn = init_db.get_connection()
    rvb._ensure_policy_events_table(conn)
    conn.close()
    return db_path


def _timeout_seconds() -> int:
    return int(execution_policy.load_policy_config()["run_timeouts_seconds"][rvb.POLICY_ID])


def _save_events(events: list[dict[str, str]]) -> None:
    conn = init_db.get_connection()
    conn.executemany(
        """INSERT INTO policy_events
               (event_time, policy_id, event_type, status, source, detail, next_run_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                event["event_time"], rvb.POLICY_ID, event["event_type"], event["status"],
                "test", json.dumps({"attempt_id": event["attempt_id"], "message": "test event"}),
                execution_policy.next_run_iso(rvb.POLICY_ID),
            )
            for event in events
        ],
    )
    conn.commit()
    conn.close()


def _event(
    event_time: datetime,
    event_type: str,
    status: str,
    attempt_id: str,
) -> dict[str, str]:
    return {
        "event_time": event_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": event_type,
        "status": status,
        "attempt_id": attempt_id,
    }


def _load_events() -> list[dict]:
    conn = init_db.get_connection()
    rows = conn.execute(
        "SELECT id, event_time, event_type, status, detail FROM policy_events "
        "WHERE policy_id = ? ORDER BY id",
        (rvb.POLICY_ID,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _run_dry_vqe(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    args = SimpleNamespace(
        defer_reason="",
        manual_override_note="",
        backend="aer",
        max_qpu_seconds=rvb.MAX_QPU_SECONDS,
        dry_run=True,
    )
    monkeypatch.setattr(rvb, "_parse_args", lambda: args)
    monkeypatch.setattr(rvb, "resolve_backend_choice", lambda *args, **kwargs: ("aer", None))
    for _ in range(count):
        with pytest.raises(SystemExit) as exc_info:
            rvb.main()
        assert exc_info.value.code == 0


@given("a prior VQE attempt passed the configured timeout without a terminal event")
def expired_attempt(vqe_database: Path) -> None:
    now = datetime.now(timezone.utc)
    timeout = _timeout_seconds()
    _save_events([
        _event(now - timedelta(seconds=timeout + 60), "run_started", "started", "expired-attempt"),
    ])


@when("two later dry-run VQE invocations process the history", target_fixture="events_after_runs")
def invoke_vqe_twice(
    monkeypatch: pytest.MonkeyPatch,
    vqe_database: Path,
) -> list[dict]:
    _run_dry_vqe(monkeypatch, count=2)
    return _load_events()


@then("one unknown marker with the prior attempt id precedes the new run start")
def assert_expired_attempt_marked_once(events_after_runs: list[dict]) -> None:
    markers = [event for event in events_after_runs if event["event_type"] == "terminal_missing"]
    assert len(markers) == 1
    assert markers[0]["status"] == "unknown"
    assert json.loads(markers[0]["detail"])["attempt_id"] == "expired-attempt"
    current_starts = [
        event for event in events_after_runs
        if event["event_type"] == "run_started"
        and json.loads(event["detail"]).get("attempt_id") != "expired-attempt"
    ]
    assert markers[0]["id"] < current_starts[0]["id"]


@given("VQE history has an expired attempt plus recent, completed, and marked attempts")
def guarded_attempts(vqe_database: Path) -> None:
    now = datetime.now(timezone.utc)
    timeout = _timeout_seconds()
    old_start = now - timedelta(seconds=timeout + 3600)
    _save_events([
        _event(now - timedelta(seconds=timeout + 60), "run_started", "started", "eligible-expired"),
        _event(now - timedelta(seconds=60), "run_started", "started", "not-expired"),
        _event(old_start, "run_started", "started", "already-completed"),
        _event(old_start + timedelta(seconds=60), "run_completed", "succeeded", "already-completed"),
        _event(old_start, "run_started", "started", "already-marked"),
        _event(old_start + timedelta(seconds=120), "terminal_missing", "unknown", "already-marked"),
    ])


@when("a later dry-run VQE invocation processes the history", target_fixture="guarded_events")
def invoke_vqe_once(
    monkeypatch: pytest.MonkeyPatch,
    vqe_database: Path,
) -> list[dict]:
    _run_dry_vqe(monkeypatch, count=1)
    return _load_events()


@then("only the eligible expired attempt receives a new marker")
def assert_guarded_attempts_not_marked(guarded_events: list[dict]) -> None:
    markers = [event for event in guarded_events if event["event_type"] == "terminal_missing"]
    marked_ids = {json.loads(event["detail"])["attempt_id"] for event in markers}
    assert marked_ids == {"eligible-expired", "already-marked"}
    assert len(markers) == 2


@given("VQE history has an unknown older attempt and a newer running attempt", target_fixture="panel_events")
def unknown_and_newer_attempts() -> list[dict]:
    return [
        {
            "event_time": "2026-10-13T12:00:00Z",
            "event_type": "run_started",
            "status": "started",
            "detail": '{"attempt_id":"newer-attempt","message":"started"}',
        },
        {
            "event_time": "2026-10-13T11:59:00Z",
            "event_type": "terminal_missing",
            "status": "unknown",
            "detail": '{"attempt_id":"older-attempt","message":"No terminal report after 7200s."}',
        },
        {
            "event_time": "2026-10-13T10:00:00Z",
            "event_type": "run_started",
            "status": "started",
            "detail": '{"attempt_id":"older-attempt","message":"started"}',
        },
    ]


@when("the existing VQE sync panel is rendered", target_fixture="panel_html")
def render_vqe_panel(panel_events: list[dict]) -> str:
    policy = dashboard._load_schedule_policy(rvb.POLICY_ID)
    return dashboard._build_sync_panel(
        rvb.POLICY_ID,
        "&#9889;",
        "VQE Monthly Benchmark",
        panel_events,
        policy,
        now_utc="2026-10-13T12:01:00Z",
    )


@then("the older attempt is unknown while the headline summarizes the newer attempt")
def assert_panel_keeps_newest_attempt_summary(panel_html: str) -> None:
    assert "Run status: <strong>ACTIVE</strong>" in panel_html
    assert "<th>Attempt ID</th>" in panel_html
    marker_row = next(row for row in panel_html.splitlines() if "terminal_missing" in row)
    assert "<td>older-attempt</td>" in marker_row
    assert "UNKNOWN" in marker_row


@then("the panel does not attribute a cause or claim provider cancellation")
def assert_panel_does_not_infer_cause_or_cancellation(panel_html: str) -> None:
    assert "cancelled by provider" not in panel_html.lower()
    assert "canceled by provider" not in panel_html.lower()