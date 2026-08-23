from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = TEST_ROOT / "tools"

spec = importlib.util.spec_from_file_location(
    "gen_benchmark_dashboard",
    TOOLS_DIR / "gen_benchmark_dashboard.py",
)
assert spec is not None
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)  # type: ignore[union-attr]


def test_load_replay_runs_keeps_ideal_and_noisy_rows_separate(tmp_path, monkeypatch):
    import init_db

    db_path = tmp_path / "quantumpsi.db"
    monkeypatch.setenv("QUANTUM_DB_PATH", str(db_path))
    monkeypatch.setenv("QUANTUM_DB_KEY", "testkey")
    monkeypatch.setattr(init_db, "DB_PATH", db_path)
    init_db.init_db()
    conn = init_db.get_connection()
    conn.execute(
        "INSERT INTO shor_replay_benchmarks VALUES "
        "(1, 'run-1', 'ideal', 15, 100, 90, .9, .83, .94, 7, '{}', '{\"model\":\"ideal\"}', 'now'), "
        "(2, 'run-1', 'noisy', 15, 100, 60, .6, .5, .7, 7, '{}', '{\"model\":\"noisy\"}', 'now')"
    )
    conn.commit()
    conn.close()
    rows = module._load_replay_runs()

    assert [row["mode"] for row in rows] == ["ideal", "noisy"]
    assert rows[0]["success_rate"] == pytest.approx(.9)
    assert rows[1]["provenance"]["model"] == "noisy"


def test_build_replay_table_labels_modes_and_confidence_interval() -> None:
    html = module._build_replay_table([
        {
            "mode": "ideal", "n_value": 15, "repetitions": 100,
            "success_rate": 0.9, "ci_95_low": 0.83, "ci_95_high": 0.94,
            "seed": 7, "provenance": {"model": "AerSimulator"},
        },
        {
            "mode": "noisy", "n_value": 15, "repetitions": 100,
            "success_rate": 0.6, "ci_95_low": 0.5, "ci_95_high": 0.7,
            "seed": 7, "provenance": {"model": "depolarizing"},
        },
    ])

    assert "Ideal / Noisy Shor Replay" in html
    assert "0.830–0.940" in html
    assert "depolarizing" in html

def test_load_cache_widget_data_sorts_sparkline_points(tmp_path, monkeypatch):
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    live_dir.mkdir(parents=True)
    (live_dir / "ty_string_cache.txt").write_text("01" * 10, encoding="utf-8")

    data_dir = root / "src" / "data"
    cache_file = data_dir / "cache_usage.jsonl"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        '{"ts":"2026-06-01T10:00:00Z","remaining":1000000}\n'
        '{"ts":"2026-05-31T23:00:00Z","remaining":1100000}\n'
        '{"ts":"2026-06-01T12:00:00Z","remaining":900000}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "_ROOT", root)
    data = module._load_cache_widget_data()

    assert [t for t, _ in data["sparkline_points"]] == [
        "2026-05-31T23:00:00Z",
        "2026-06-01T10:00:00Z",
        "2026-06-01T12:00:00Z",
    ]
    assert data["last_fill_peak"] == 1100000
    assert data["current_bits"] == 20
    assert data["pct_consumed"] == pytest.approx((1100000 - 20) / 1100000 * 100)


def test_load_cache_widget_data_includes_backup_fill_date(tmp_path, monkeypatch):
    root = tmp_path / "quantum"
    live_dir = root / "src" / "data" / "liveCache"
    live_dir.mkdir(parents=True)
    (live_dir / "ty_string_cache.txt").write_text("01" * 10, encoding="utf-8")

    data_dir = root / "src" / "data"
    cache_file = data_dir / "cache_usage.jsonl"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        '{"ts":"2026-04-15T18:43:03Z","remaining":1000}\n',
        encoding="utf-8",
    )

    backup_dir = root / "qbackups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "ty_string_cache_20260601_080334.txt"
    backup_path.write_bytes(b"0" * 2000)

    monkeypatch.setattr(module, "_ROOT", root)
    data = module._load_cache_widget_data()

    assert any(ts == "2026-06-01T08:03:34Z" for ts, _ in data["sparkline_points"])
    assert data["last_fill_peak"] == 2000
    assert data["sparkline_points"][-1][0] == "2026-06-01T08:03:34Z"
