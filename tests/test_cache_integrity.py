from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import cache_integrity  # noqa: E402


def test_atomic_replace_writes_valid_cache_manifest_and_backup_lineage(tmp_path: Path) -> None:
    live_cache = tmp_path / "liveCache" / "ty_string_cache.txt"
    backup_dir = tmp_path / "qbackups"
    live_cache.parent.mkdir()
    live_cache.write_text("01\n", encoding="utf-8")

    result = cache_integrity.atomic_replace_cache(
        live_cache,
        backup_dir,
        ["10", "11"],
        now="20260830_120000",
    )

    assert live_cache.read_text(encoding="utf-8") == "10\n11\n"
    assert result.bit_count == 4
    assert result.manifest_path.exists()
    assert result.backup_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bit_count"] == 4
    assert manifest["line_count"] == 2
    assert manifest["parent_backup"] == result.backup_path.name
    assert len(manifest["sha256"]) == 64


def test_validate_cache_reports_malformed_lines_without_counting_them(tmp_path: Path) -> None:
    cache_path = tmp_path / "ty_string_cache.txt"
    cache_path.write_text("01\n0102\n\n1 0\n", encoding="utf-8")

    validation = cache_integrity.validate_cache(cache_path)

    assert validation.valid is False
    assert validation.bit_count == 2
    assert validation.valid_line_count == 1
    assert validation.malformed_lines == (2, 4)


def test_quarantine_cache_moves_malformed_source_and_preserves_audit_metadata(tmp_path: Path) -> None:
    cache_path = tmp_path / "ty_string_cache.txt"
    quarantine_dir = tmp_path / "quarantine"
    cache_path.write_text("01\nnot-bits\n", encoding="utf-8")

    quarantined = cache_integrity.quarantine_cache(cache_path, quarantine_dir, now="20260830_120001")

    assert not cache_path.exists()
    assert quarantined.exists()
    assert quarantined.parent == quarantine_dir
    assert quarantined.read_text(encoding="utf-8") == "01\nnot-bits\n"
    assert quarantined.with_suffix(".json").exists()


def test_verify_cache_is_read_only_and_returns_public_integrity_status(tmp_path: Path) -> None:
    cache_path = tmp_path / "ty_string_cache.txt"
    cache_path.write_text("01\n10\n", encoding="utf-8")
    manifest = cache_integrity.write_manifest(cache_path)
    before = cache_path.stat().st_mtime_ns

    status = cache_integrity.verify_cache(cache_path, manifest)

    assert status["valid"] is True
    assert status["bit_count"] == 4
    assert status["source"] == "quantum"
    assert "sha256" not in status
    assert cache_path.stat().st_mtime_ns == before


def test_validate_cache_rejects_missing_cache(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        cache_integrity.validate_cache(tmp_path / "missing.txt")


def test_runtime_status_reports_verified_quantum_provenance_without_hash(tmp_path: Path) -> None:
    cache_path = tmp_path / "ty_string_cache.txt"
    cache_path.write_text("01\n10\n", encoding="utf-8")
    manifest_path = cache_integrity.write_manifest(cache_path)
    sys.path.insert(0, str(_PROJECT_ROOT / "src" / "utils"))
    import quantum_rt  # noqa: PLC0415

    status = quantum_rt.cache_integrity_status(cache_path, manifest_path)

    assert status["source"] == "quantum"
    assert status["verified"] is True
    assert "sha256" not in status


def test_verify_cache_cli_is_read_only_and_prints_status(tmp_path: Path, capsys) -> None:
    cache_path = tmp_path / "ty_string_cache.txt"
    cache_path.write_text("01\n10\n", encoding="utf-8")
    cache_integrity.write_manifest(cache_path)
    import verify_cache  # noqa: PLC0415

    assert verify_cache.main(["--cache", str(cache_path)]) == 0
    output = capsys.readouterr().out
    assert "verified=true" in output
    assert "sha256" not in output