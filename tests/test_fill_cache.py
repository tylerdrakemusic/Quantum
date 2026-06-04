from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fill_cache",
    Path(__file__).resolve().parent.parent / "tools" / "fill_cache.py",
)
assert spec is not None
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)  # type: ignore[union-attr]


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
    assert backups[0].read_text(encoding="utf-8") == live_cache.read_text(encoding="utf-8")
