from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "utils"))

import init_db  # noqa: E402
from shor_ideal_noisy_analysis import (
    analyze_trials,
    persist_replay_results,
    run_benchmark,
    run_seeded_replay,
)


def test_analyze_trials_reports_success_wilson_and_order_statistics() -> None:
    result = analyze_trials(
        [
            {"success": True, "order": 4},
            {"success": True, "order": 4},
            {"success": False, "order": None},
            {"success": True, "order": 2},
        ],
        mode="ideal",
        repetitions=4,
        seed=17,
        provenance={"model": "statevector", "version": "test"},
    )

    assert result["mode"] == "ideal"
    assert result["repetitions"] == 4
    assert result["successes"] == 3
    assert result["success_rate"] == pytest.approx(0.75)
    assert result["success_rate_ci_95"] == pytest.approx(
        (0.30064184258240184, 0.9544127391902995)
    )
    assert result["order_summary"] == {
        "count": 3,
        "mean": pytest.approx(10 / 3),
        "variance": pytest.approx(4 / 3),
        "distribution": {"2": 1, "4": 2},
    }
    assert result["provenance"] == {"model": "statevector", "version": "test"}


def test_run_seeded_replay_is_deterministic_and_separates_modes() -> None:
    def sampler(mode: str, random_source: object) -> dict[str, object]:
        value = random_source.random()  # type: ignore[attr-defined]
        return {"success": value >= 0.5, "order": 4 if value >= 0.5 else None}

    first = run_seeded_replay(
        repetitions=8,
        seed=23,
        sampler=sampler,
        provenance={"model": "test", "version": "1"},
    )
    second = run_seeded_replay(
        repetitions=8,
        seed=23,
        sampler=sampler,
        provenance={"model": "test", "version": "1"},
    )

    assert first == second
    assert set(first) == {"ideal", "noisy"}
    assert all(result["repetitions"] == 8 for result in first.values())


def test_persist_replay_results_writes_one_provenance_row_per_mode(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()

    results = {
        "ideal": analyze_trials(
            [{"success": True, "order": 4}],
            mode="ideal",
            repetitions=1,
            seed=3,
            provenance={"model": "statevector", "version": "1"},
        ),
        "noisy": analyze_trials(
            [{"success": False, "order": None}],
            mode="noisy",
            repetitions=1,
            seed=3,
            provenance={"model": "depolarizing", "version": "1"},
        ),
    }

    persist_replay_results(results, n_value=15)

    conn = init_db.get_connection()
    rows = conn.execute(
        "SELECT mode, n_value, success_rate, seed, provenance_json "
        "FROM shor_replay_benchmarks ORDER BY mode"
    ).fetchall()
    conn.close()
    assert [(row["mode"], row["n_value"], row["success_rate"], row["seed"]) for row in rows] == [
        ("ideal", 15, 1.0, 3),
        ("noisy", 15, 0.0, 3),
    ]
    assert '"model": "statevector"' in rows[0]["provenance_json"]


def test_run_benchmark_defaults_to_100_offline_repetitions(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def sampler(mode: str, random_source: object) -> dict[str, object]:
        calls.append((mode, 1))
        return {"success": True, "order": 4}

    monkeypatch.setattr("shor_ideal_noisy_analysis._default_sampler", sampler)
    monkeypatch.setattr("shor_ideal_noisy_analysis.persist_replay_results", lambda *a, **k: None)

    results = run_benchmark(seed=41, persist=False)

    assert len(calls) == 200
    assert all(value["repetitions"] == 100 for value in results.values())