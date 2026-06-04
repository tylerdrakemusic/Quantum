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
