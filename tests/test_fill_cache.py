from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))
import init_db  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "fill_cache",
    Path(__file__).resolve().parent.parent / "tools" / "fill_cache.py",
)
assert spec is not None
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)  # type: ignore[union-attr]


@pytest.fixture
def quantum_db_env(tmp_path, monkeypatch):
    """Real sqlite job_retry_status DB so RetrySupervisor wiring can persist status."""
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    yield db_path


class _FakeSamplerResult:
    def __init__(self, counts: dict[str, int], execution_seconds: float = 1.0) -> None:
        self.metadata = {"execution": {"execution_spans_seconds": execution_seconds}}
        self._counts = counts

    def get_counts(self) -> dict[str, int]:
        return self._counts


def _patch_ibm_connect(monkeypatch, runtime_exceptions=None):
    monkeypatch.setattr(module, "_get_ibm_credentials", lambda: ("key", "instance"))

    fake_backend = MagicMock()
    fake_backend.name = "fake-backend"
    fake_backend.num_qubits = 127
    fake_backend.status.return_value = MagicMock(pending_jobs=0)
    monkeypatch.setattr(module, "_get_backend", lambda service: fake_backend)
    monkeypatch.setattr(module, "_build_h_circuit", lambda n: MagicMock())

    fake_transpiled = MagicMock()
    fake_pm = MagicMock(run=MagicMock(return_value=fake_transpiled))

    qiskit_module = MagicMock()
    qiskit_transpiler = MagicMock()
    qiskit_preset_passmanagers = MagicMock(generate_preset_pass_manager=MagicMock(return_value=fake_pm))
    qiskit_module.transpiler = qiskit_transpiler
    qiskit_transpiler.preset_passmanagers = qiskit_preset_passmanagers
    monkeypatch.setitem(sys.modules, "qiskit", qiskit_module)
    monkeypatch.setitem(sys.modules, "qiskit.transpiler", qiskit_transpiler)
    monkeypatch.setitem(sys.modules, "qiskit.transpiler.preset_passmanagers", qiskit_preset_passmanagers)

    ibm_runtime = MagicMock()
    ibm_runtime.QiskitRuntimeService.return_value = MagicMock()
    monkeypatch.setitem(sys.modules, "qiskit_ibm_runtime", ibm_runtime)
    if runtime_exceptions is None:
        runtime_exceptions = ModuleType("qiskit_ibm_runtime.exceptions")
        for name in ("JobTimeoutError", "RuntimeJobMaxTimeoutError", "RuntimeJobTimeoutError"):
            setattr(runtime_exceptions, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "qiskit_ibm_runtime.exceptions", runtime_exceptions)
    return ibm_runtime


def test_persist_cache_fill_appends_to_live_cache_and_writes_backup(tmp_path, monkeypatch):
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    live_dir.mkdir(parents=True, exist_ok=True)

    live_cache = live_dir / "ty_string_cache.txt"
    live_cache.write_text("01\n", encoding="utf-8")

    backup_dir = root / "qbackups"
    capacity_file = live_dir / "ty_string_cache_capacity.txt"

    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_cache)
    monkeypatch.setattr(module, "_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", capacity_file)

    total_bits = module._persist_cache_fill(["10", "11"])

    assert total_bits == 4
    assert live_cache.read_text(encoding="utf-8").splitlines() == ["01", "10", "11"]
    assert capacity_file.read_text(encoding="utf-8").strip() == str(live_cache.stat().st_size)

    backups = list(backup_dir.glob("ty_string_cache_*.txt"))
    assert len(backups) == 1


def test_persist_cache_fill_quarantines_malformed_live_cache_before_replacement(tmp_path, monkeypatch):
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_cache = live_dir / "ty_string_cache.txt"
    live_cache.write_text("01\ncorrupt\n", encoding="utf-8")

    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_cache)
    monkeypatch.setattr(module, "_BACKUP_DIR", root / "qbackups")
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", live_dir / "ty_string_cache_capacity.txt")

    module._persist_cache_fill(["10"])

    assert live_cache.read_text(encoding="utf-8") == "10\n"
    quarantined = list((root / "qbackups" / "quarantine").glob("*.txt"))
    assert len(quarantined) == 1


def test_main_starts_one_elapsed_timer_and_records_success_duration(monkeypatch):
    events: list[dict[str, str]] = []
    monotonic_values = iter([10.0, 12.5])
    monotonic_calls: list[None] = []

    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: type("Args", (), {"status": False, "dry_run": False, "max_qpu_seconds": 5})(),
    )

    def _monotonic() -> float:
        monotonic_calls.append(None)
        return next(monotonic_values)

    monkeypatch.setattr(module.time, "monotonic", _monotonic)
    monkeypatch.setattr(module, "run_fill", lambda max_qpu_seconds, dry_run: 8)
    monkeypatch.setattr(
        module,
        "_log_policy_event",
        lambda **kwargs: events.append(kwargs),
    )

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 0
    completed = events[-1]
    assert completed["event_type"] == "run_completed"
    assert completed["status"] == "succeeded"
    assert "elapsed_seconds=2.500" in completed["detail"]
    started = next(event for event in events if event["event_type"] == "run_started")
    assert started["attempt_id"]
    assert started["attempt_id"] == completed["attempt_id"]
    assert len(monotonic_calls) == 2


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        pytest.param("dry-run", "skipped", id="dry-run"),
        pytest.param("zero-bits", "failed", id="zero-bits"),
        pytest.param("interruption", "deferred", id="interruption"),
        pytest.param("failure", "failed", id="exception"),
    ],
)
def test_main_records_non_negative_elapsed_duration_for_completion_outcomes(
    monkeypatch, outcome, expected_status,
):
    events: list[dict[str, str]] = []
    monotonic_values = iter([10.0, 9.0])
    monotonic_calls: list[None] = []

    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: type(
            "Args",
            (),
            {"status": False, "dry_run": outcome == "dry-run", "max_qpu_seconds": 5},
        )(),
    )

    def _monotonic() -> float:
        monotonic_calls.append(None)
        return next(monotonic_values)

    monkeypatch.setattr(module.time, "monotonic", _monotonic)
    monkeypatch.setattr(module, "_log_policy_event", lambda **kwargs: events.append(kwargs))

    def _run_fill(max_qpu_seconds, dry_run):
        if outcome == "interruption":
            raise KeyboardInterrupt
        if outcome == "failure":
            raise RuntimeError("simulated failure")
        return 0

    monkeypatch.setattr(module, "run_fill", _run_fill)

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == (1 if outcome in {"zero-bits", "interruption", "failure"} else 0)
    completed = events[-1]
    assert completed["event_type"] == "run_completed"
    assert completed["status"] == expected_status
    assert "elapsed_seconds=0.000" in completed["detail"]
    assert len(monotonic_calls) == 2


def test_run_fill_wired_through_retry_supervisor_records_ibm_job_status(
    monkeypatch, quantum_db_env, tmp_path,
):
    """A successful fill job must be enqueued as a Job(backend='ibm') and
    routed through RetrySupervisor — verified via job_retry_status, not by
    mocking Sampler.run/backend.run directly."""
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_dir / "ty_string_cache.txt")
    monkeypatch.setattr(module, "_BACKUP_DIR", root / "qbackups")
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", live_dir / "ty_string_cache_capacity.txt")

    ibm_runtime = _patch_ibm_connect(monkeypatch)
    fake_job = MagicMock()
    fake_job.result.return_value = _FakeSamplerResult({"01": 2}, execution_seconds=5.0)
    ibm_runtime.SamplerV2.return_value = MagicMock(run=MagicMock(return_value=fake_job))

    total_bits = module.run_fill(max_qpu_seconds=5, dry_run=False)

    assert total_bits > 0

    conn = init_db.get_connection()
    rows = conn.execute(
        "SELECT job_id, status, backend FROM job_retry_status"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    row = rows[0]
    assert row is not None
    assert row["job_id"].startswith("fill-cache-")
    assert row["job_id"].endswith("-1")
    assert row["status"] == "succeeded"
    assert row["backend"] == "ibm"


def test_run_fill_uses_distinct_job_ids_across_invocations(
    monkeypatch, quantum_db_env, tmp_path,
):
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_dir / "ty_string_cache.txt")
    monkeypatch.setattr(module, "_BACKUP_DIR", root / "qbackups")
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", live_dir / "capacity.txt")

    ibm_runtime = _patch_ibm_connect(monkeypatch)
    fake_job = MagicMock()
    fake_job.result.return_value = _FakeSamplerResult({"01": 2}, execution_seconds=5.0)
    sampler = MagicMock(run=MagicMock(return_value=fake_job))
    ibm_runtime.SamplerV2.return_value = sampler

    assert module.run_fill(max_qpu_seconds=5, dry_run=False) > 0
    assert module.run_fill(max_qpu_seconds=5, dry_run=False) > 0

    conn = init_db.get_connection()
    rows = conn.execute(
        "SELECT job_id, status FROM job_retry_status ORDER BY job_id"
    ).fetchall()
    conn.close()

    job_ids = [row["job_id"] for row in rows]
    assert len(job_ids) == 2
    assert len(set(job_ids)) == 2
    assert all(job_id.startswith("fill-cache-") and job_id.endswith("-1") for job_id in job_ids)
    assert len({job_id.rsplit("-", 1)[0] for job_id in job_ids}) == 2
    assert all(row["status"] == "succeeded" for row in rows)


def test_run_fill_stops_successfully_at_supervisor_ibm_call_cap(
    monkeypatch, quantum_db_env, tmp_path,
):
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    live_dir.mkdir(parents=True)
    (live_dir / "ty_string_cache.txt").write_text("11\n", encoding="utf-8")
    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_dir / "ty_string_cache.txt")
    monkeypatch.setattr(module, "_BACKUP_DIR", root / "qbackups")
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", live_dir / "capacity.txt")
    ibm_runtime = _patch_ibm_connect(monkeypatch)

    sampler = MagicMock()

    def successful_job(*_args, **_kwargs):
        job = MagicMock()
        job.result.return_value = _FakeSamplerResult({"01": 1}, execution_seconds=3.0)
        return job

    sampler.run.side_effect = successful_job
    ibm_runtime.SamplerV2.return_value = sampler

    total_bits = module.run_fill(max_qpu_seconds=180, dry_run=False)

    assert total_bits == 20
    assert sampler.run.call_count == 10
    assert module._LIVE_CACHE.read_text(encoding="utf-8").splitlines() == ["11"] + ["01"] * 10
    assert len(list((root / "qbackups").glob("ty_string_cache_*.txt"))) == 1
    conn = init_db.get_connection()
    rows = conn.execute(
        "SELECT job_id, status FROM job_retry_status ORDER BY job_id"
    ).fetchall()
    conn.close()
    assert len(rows) == 10
    assert all(row["status"] == "succeeded" for row in rows)


def test_run_fill_permanent_job_failure_raises_but_keeps_partial_success(
    monkeypatch, quantum_db_env, tmp_path,
):
    """If a later job in the batch fails permanently, run_fill must raise
    (so main() exits non-zero) but must NOT discard bits already collected
    from earlier successful jobs in the same batch run."""
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_dir / "ty_string_cache.txt")
    monkeypatch.setattr(module, "_BACKUP_DIR", root / "qbackups")
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", live_dir / "ty_string_cache_capacity.txt")

    ibm_runtime = _patch_ibm_connect(monkeypatch)

    call_count = {"n": 0}

    def _run_side_effect(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            job = MagicMock()
            job.result.return_value = _FakeSamplerResult({"01": 2}, execution_seconds=1.0)
            return job
        raise RuntimeError("simulated permanent backend failure")

    ibm_runtime.SamplerV2.return_value = MagicMock(run=MagicMock(side_effect=_run_side_effect))

    import job_retry_supervisor
    monkeypatch.setattr(job_retry_supervisor.time, "sleep", lambda *_a, **_kw: None)

    with pytest.raises(RuntimeError, match=r"fill-cache-.+-2"):
        module.run_fill(max_qpu_seconds=100, dry_run=False)

    live_cache = live_dir / "ty_string_cache.txt"
    assert live_cache.exists()
    assert live_cache.read_text(encoding="utf-8").strip() != ""

    conn = init_db.get_connection()
    rows = conn.execute(
        "SELECT job_id, status FROM job_retry_status ORDER BY job_id"
    ).fetchall()
    conn.close()
    assert len({r["job_id"].rsplit("-", 1)[0] for r in rows}) == 1
    statuses = {r["job_id"].rsplit("-", 1)[1]: r["status"] for r in rows}
    assert set(statuses) == {"1", "2"}
    assert statuses["1"] == "succeeded"
    assert statuses["2"] == "failed"


@pytest.mark.parametrize(
    "timeout_type",
    [
        pytest.param("builtin", id="builtin-timeout"),
        pytest.param("ibm-runtime", id="ibm-runtime-timeout"),
    ],
)
def test_main_records_terminal_failure_when_provider_result_wait_times_out(
    monkeypatch,
    quantum_db_env,
    tmp_path,
    request,
    timeout_type,
):
    timeout_error_type = TimeoutError
    runtime_exceptions = None
    original_runtime_modules = {
        name: value
        for name, value in sys.modules.items()
        if name == "qiskit_ibm_runtime" or name.startswith("qiskit_ibm_runtime.")
    }

    def restore_runtime_modules():
        monkeypatch.undo()
        for name in tuple(sys.modules):
            if (
                (name == "qiskit_ibm_runtime" or name.startswith("qiskit_ibm_runtime."))
                and name not in original_runtime_modules
            ):
                sys.modules.pop(name, None)
        sys.modules.update(original_runtime_modules)

    request.addfinalizer(restore_runtime_modules)
    from qiskit_ibm_runtime import exceptions as runtime_exceptions
    from qiskit_ibm_runtime.exceptions import RuntimeJobTimeoutError

    if timeout_type == "ibm-runtime":
        timeout_error_type = RuntimeJobTimeoutError

    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    live_dir.mkdir(parents=True)
    live_cache = live_dir / "ty_string_cache.txt"
    live_cache.write_text("11\n", encoding="utf-8")
    monkeypatch.setattr(module, "_ROOT", root)
    monkeypatch.setattr(module, "_LIVE_DIR", live_dir)
    monkeypatch.setattr(module, "_LIVE_CACHE", live_cache)
    monkeypatch.setattr(module, "_BACKUP_DIR", root / "qbackups")
    monkeypatch.setattr(module, "_CAPACITY_BASELINE", live_dir / "capacity.txt")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: type(
            "Args",
            (),
            {"status": False, "dry_run": False, "max_qpu_seconds": 180},
        )(),
    )

    ibm_runtime = _patch_ibm_connect(monkeypatch, runtime_exceptions)
    fake_job = MagicMock()
    observed_timeouts = []

    def timeout_result(*, timeout=None):
        observed_timeouts.append(timeout)
        raise timeout_error_type("provider wait expired")

    fake_job.result.side_effect = timeout_result
    sampler = MagicMock()
    sampler.run.return_value = fake_job
    ibm_runtime.SamplerV2.return_value = sampler

    import job_retry_supervisor
    monkeypatch.setattr(job_retry_supervisor.time, "sleep", lambda *_args: None)

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 1
    sampler.run.assert_called_once()
    assert len(observed_timeouts) == 1
    assert 0 < observed_timeouts[0] < 600
    fake_job.cancel.assert_not_called()
    assert live_cache.read_text(encoding="utf-8") == "11\n"

    conn = init_db.get_connection()
    terminal = conn.execute(
        "SELECT status, detail FROM policy_events "
        "WHERE policy_id = ? AND event_type = 'run_completed'",
        (module.POLICY_ID,),
    ).fetchone()
    retry_status = conn.execute(
        "SELECT job_id, status, error_msg FROM job_retry_status"
    ).fetchone()
    conn.close()

    assert terminal["status"] == "failed"
    assert "provider cancellation is not inferred" in terminal["detail"]
    assert retry_status["job_id"].startswith("fill-cache-")
    assert retry_status["job_id"].endswith("-1")
    assert retry_status["status"] == "failed"
    assert "provider wait expired" in retry_status["error_msg"]
