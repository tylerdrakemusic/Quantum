from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from pytest_bdd import given, scenarios, then, when

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import fill_cache  # noqa: E402
import init_db  # noqa: E402
import run_shors_bench as shors  # noqa: E402
import run_vqe_bench as vqe  # noqa: E402
from sync_scheduled_tasks import sync_policy_tasks  # noqa: E402

scenarios("quantum_scheduled_runs.feature")


@pytest.fixture
def isolated_quantum_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    return db_path


def _policy_events() -> list[dict[str, str]]:
    conn = init_db.get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT event_time, policy_id, event_type, status, detail "
            "FROM policy_events ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()


@given("the configured monthly Quantum schedules", target_fixture="monthly_policy")
def monthly_policy() -> dict:
    return json.loads(
        (PROJECT_ROOT / "src" / "config" / "execution_policy.json").read_text(encoding="utf-8")
    )


def _monthly_start_boundaries(
    monthly_policy: dict,
    now_utc: datetime,
    task_names: dict[str, str],
) -> dict[str, str]:
    definitions = dict(sync_policy_tasks(
        monthly_policy,
        PROJECT_ROOT,
        now_utc=now_utc,
        task_name_suffix="-bdd",
    ))
    namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    return {
        name: ET.fromstring(definitions[f"{task_name}-bdd"]).findtext(
            "task:Triggers/task:CalendarTrigger/task:StartBoundary", namespaces=namespace,
        )
        for name, task_name in task_names.items()
    }


@when("next runs are calculated after a summer date", target_fixture="utc_next_runs")
def calculate_summer_next_runs(monthly_policy: dict) -> dict[str, str]:
    return _monthly_start_boundaries(
        monthly_policy,
        datetime(2026, 8, 2, tzinfo=timezone.utc),
        {
            "cache": "QuantumCacheFill_Monthly",
            "shor": "ShorsMonthlyBench",
            "vqe": "VQEMonthlyBench",
        },
    )


@when(
    "next runs are calculated after a Mountain standard-time date",
    target_fixture="standard_time_next_runs",
)
def calculate_standard_time_next_runs(monthly_policy: dict) -> dict[str, str]:
    return _monthly_start_boundaries(
        monthly_policy,
        datetime(2026, 11, 2, 7, tzinfo=timezone.utc),
        {
            "cache": "QuantumCacheFill_Monthly",
            "shor": "ShorsMonthlyBench",
        },
    )


@then("cache fill, Shor, and VQE resolve to their configured UTC instants")
def assert_utc_next_runs(utc_next_runs: dict[str, str]) -> None:
    assert utc_next_runs == {
        "cache": "2026-09-01T07:00:00Z",
        "shor": "2026-09-01T08:00:00Z",
        "vqe": "2026-08-15T03:00:00Z",
    }


@then("cache fill and Shor resolve to their configured UTC instants")
def assert_standard_time_utc_next_runs(standard_time_next_runs: dict[str, str]) -> None:
    assert standard_time_next_runs == {
        "cache": "2026-12-01T07:00:00Z",
        "shor": "2026-12-01T08:00:00Z",
    }


@given(
    "a successful cache-fill provider result and an isolated Quantum database",
    target_fixture="cache_db_path",
)
def successful_cache_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_quantum_db: Path,
) -> None:
    live_dir = tmp_path / "liveCache"
    backup_dir = tmp_path / "qbackups"
    live_dir.mkdir()
    monkeypatch.setattr(fill_cache, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(fill_cache, "_LIVE_CACHE", live_dir / "ty_string_cache.txt")
    monkeypatch.setattr(fill_cache, "_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(fill_cache, "_CAPACITY_BASELINE", live_dir / "capacity.txt")
    fill_cache._LIVE_CACHE.write_text("11\n", encoding="utf-8")
    monkeypatch.setattr(
        fill_cache,
        "_parse_args",
        lambda: SimpleNamespace(status=False, dry_run=False, max_qpu_seconds=180),
    )
    monkeypatch.setattr(
        fill_cache,
        "run_fill",
        lambda max_qpu_seconds, dry_run: fill_cache._persist_cache_fill(["01", "10"]),
    )
    return isolated_quantum_db


@when("the cache-fill runner completes", target_fixture="cache_exit_code")
def run_cache_fill(cache_db_path: Path) -> int:
    with pytest.raises(SystemExit) as exc_info:
        fill_cache.main()
    return int(exc_info.value.code)


@then("the cache has a backup and an attempt-correlated successful terminal event")
def assert_cache_fill_success(cache_exit_code: int) -> None:
    assert cache_exit_code == 0
    assert fill_cache._LIVE_CACHE.read_text(encoding="utf-8").splitlines() == ["11", "01", "10"]
    assert len(list(fill_cache._BACKUP_DIR.glob("ty_string_cache_*.txt"))) == 1
    terminal = next(event for event in _policy_events() if event["event_type"] == "run_completed")
    detail = json.loads(terminal["detail"])
    assert terminal["status"] == "succeeded"
    assert detail["attempt_id"]


@given(
    "successful H2 and LiH results and an isolated Quantum database",
    target_fixture="vqe_db_path",
)
def successful_vqe_results(
    monkeypatch: pytest.MonkeyPatch,
    isolated_quantum_db: Path,
) -> None:
    monkeypatch.setattr(
        vqe,
        "_parse_args",
        lambda: SimpleNamespace(
            defer_reason="", manual_override_note="", backend="aer",
            max_qpu_seconds=600, dry_run=False, molecule="all", ansatz="UCCSD",
            seed=17, no_dashboard=True,
        ),
    )
    monkeypatch.setattr(vqe, "resolve_backend_choice", lambda *args, **kwargs: ("aer", None))
    monkeypatch.setattr(
        vqe,
        "run_all_molecules",
        lambda *args, **kwargs: ([
            {"molecule": "H2", "ac_met": True},
            {"molecule": "LiH", "ac_met": True},
        ], False, False),
    )
    return isolated_quantum_db


@when("the VQE scheduled runner completes", target_fixture="vqe_exit_code")
def run_vqe(vqe_db_path: Path) -> int:
    with pytest.raises(SystemExit) as exc_info:
        vqe.main()
    return int(exc_info.value.code)


@then("one attempt-correlated successful terminal event names both molecules")
def assert_vqe_success(vqe_exit_code: int) -> None:
    assert vqe_exit_code == 0
    terminal = next(
        event for event in _policy_events()
        if event["policy_id"] == vqe.POLICY_ID and event["event_type"] == "run_completed"
    )
    detail = json.loads(terminal["detail"])
    assert terminal["status"] == "succeeded"
    assert detail["attempt_id"]
    assert "H2, LiH" in detail["message"]
    assert "all_ac_met=True" in detail["message"]


@given(
    "a scheduled Shor run with the policy approval and an isolated Quantum database",
    target_fixture="shor_run_state",
)
def successful_shor_result(
    monkeypatch: pytest.MonkeyPatch,
    isolated_quantum_db: Path,
) -> None:
    args = SimpleNamespace(
        n=15, max_qpu_seconds=300, dry_run=False, defer_reason="",
        manual_override_note="", approved=False, scheduled=True,
        now_utc="2026-09-01T08:00:00Z",
    )
    monkeypatch.setattr(shors, "_parse_args", lambda: args)
    captured: dict[str, object] = {}

    def run_approved_benchmark(**kwargs) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "planner_status": "runnable_hardware_plan",
            "success": True,
            "n_value": 15,
            "n_qubits": 8,
            "factor_found": "3,5",
            "qpu_seconds": 2.0,
            "backend": "ibm-test",
        }

    monkeypatch.setattr(shors, "run_benchmark", run_approved_benchmark)
    monkeypatch.setattr(shors, "persist_result", lambda result: 1)
    monkeypatch.setattr(shors, "print_db_row", lambda row_id: None)
    monkeypatch.setattr(shors.subprocess, "run", lambda *args, **kwargs: None)
    return captured


@when("the Shor scheduled runner completes with factors 3 and 5", target_fixture="shor_run_state")
def run_shors(shor_run_state: dict[str, object]) -> dict[str, object]:
    with pytest.raises(SystemExit) as exc_info:
        shors.main()
    shor_run_state["exit_code"] = int(exc_info.value.code)
    return shor_run_state


@then("it records an approved hardware success and exits zero")
def assert_shor_success(shor_run_state: dict[str, object]) -> None:
    assert shor_run_state["approved"] is True
    assert shor_run_state["exit_code"] == 0
    terminal = next(
        event for event in _policy_events()
        if event["policy_id"] == shors.POLICY_ID and event["event_type"] == "run_completed"
    )
    detail = json.loads(terminal["detail"])
    assert terminal["status"] == "succeeded"
    assert detail["attempt_id"]


@given(
    "an out-of-window Shor run and an isolated Quantum database",
    target_fixture="deferred_shor_state",
)
def out_of_window_shor_run(
    monkeypatch: pytest.MonkeyPatch,
    isolated_quantum_db: Path,
) -> dict[str, object]:
    args = SimpleNamespace(
        n=15,
        max_qpu_seconds=300,
        dry_run=False,
        defer_reason="",
        manual_override_note="",
        approved=True,
        scheduled=True,
        now_utc="2026-09-01T09:00:01Z",
    )
    fake_circuit = SimpleNamespace(depth=lambda: 1, count_ops=lambda: {"x": 1})
    monkeypatch.setattr(shors, "_parse_args", lambda: args)
    monkeypatch.setattr(shors, "_build_shor_circuit_n15", lambda _n_count: (fake_circuit, 8))
    monkeypatch.setattr(
        shors,
        "_load_backend_snapshots",
        lambda *_args: pytest.fail("out-of-window plans must not read backend health"),
    )
    monkeypatch.setattr(
        shors,
        "_get_ibm_credentials",
        lambda: pytest.fail("out-of-window plans must not access provider credentials"),
    )
    return {"exit_code": -1}


@when("the scheduled Shor benchmark is planned", target_fixture="deferred_shor_state")
def plan_out_of_window_shor(deferred_shor_state: dict[str, object]) -> dict[str, object]:
    with pytest.raises(SystemExit) as exc_info:
        shors.main()
    deferred_shor_state["exit_code"] = int(exc_info.value.code)
    deferred_shor_state["events"] = _policy_events()
    return deferred_shor_state


@then("it records a deferred terminal outcome without reporting success")
def assert_shor_terminal_deferred(deferred_shor_state: dict[str, object]) -> None:
    events = deferred_shor_state["events"]
    assert deferred_shor_state["exit_code"] == 0
    assert any(
        event["event_type"] == "planner_deferred" and event["status"] == "deferred"
        for event in events
    )
    terminal_events = [
        event for event in events
        if event["policy_id"] == shors.POLICY_ID
        and event["event_type"] == "run_completed"
    ]
    assert [event["status"] for event in terminal_events] == ["deferred"]
    assert all(event["status"] != "succeeded" for event in events)