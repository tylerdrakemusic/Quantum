"""Integrity and provenance helpers for the quantum bitstring cache."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class CacheValidation:
    """Validation results for a cache file."""

    valid: bool
    bit_count: int
    valid_line_count: int
    malformed_lines: tuple[int, ...]


@dataclass(frozen=True)
class CacheReplacement:
    """Files and counts produced by an atomic cache replacement."""

    bit_count: int
    manifest_path: Path
    backup_path: Path | None


def manifest_path_for(cache_path: Path) -> Path:
    """Return the sidecar manifest path for a cache path."""
    return cache_path.with_suffix(".manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_cache(cache_path: Path) -> CacheValidation:
    """Validate non-empty cache lines and count only strict binary lines."""
    if not cache_path.exists():
        raise FileNotFoundError(cache_path)
    bit_count = 0
    valid_line_count = 0
    malformed_lines: list[int] = []
    with cache_path.open(encoding="utf-8", errors="replace") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if set(line) <= {"0", "1"}:
                bit_count += len(line)
                valid_line_count += 1
            else:
                malformed_lines.append(line_number)
    return CacheValidation(
        valid=not malformed_lines and valid_line_count > 0,
        bit_count=bit_count,
        valid_line_count=valid_line_count,
        malformed_lines=tuple(malformed_lines),
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_manifest(cache_path: Path, *, parent_backup: str | None = None) -> Path:
    """Write an integrity manifest atomically and return its path."""
    validation = validate_cache(cache_path)
    if not validation.valid:
        raise ValueError("cannot manifest a cache containing malformed or empty data")
    manifest = {
        "format": 1,
        "cache_file": cache_path.name,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bit_count": validation.bit_count,
        "line_count": validation.valid_line_count,
        "sha256": _sha256(cache_path),
        "parent_backup": parent_backup,
    }
    path = manifest_path_for(cache_path)
    _atomic_write(path, json.dumps(manifest, sort_keys=True) + "\n")
    return path


def atomic_replace_cache(
    cache_path: Path,
    backup_dir: Path,
    bitstrings: list[str],
    *,
    now: str | None = None,
) -> CacheReplacement:
    """Snapshot the current cache, then atomically replace it with valid data."""
    if not bitstrings or any(not value or set(value) - {"0", "1"} for value in bitstrings):
        raise ValueError("replacement data must contain non-empty binary strings")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_path: Path | None = None
    if cache_path.exists():
        backup_path = backup_dir / f"{cache_path.stem}_{timestamp}{cache_path.suffix}"
        backup_path.write_bytes(cache_path.read_bytes())
        write_manifest(backup_path)
    content = "".join(f"{value}\n" for value in bitstrings)
    temporary_path = cache_path.with_name(f".{cache_path.name}.replacement")
    _atomic_write(temporary_path, content)
    os.replace(temporary_path, cache_path)
    manifest_path = write_manifest(cache_path, parent_backup=backup_path.name if backup_path else None)
    return CacheReplacement(
        bit_count=sum(len(value) for value in bitstrings),
        manifest_path=manifest_path,
        backup_path=backup_path,
    )


def quarantine_cache(cache_path: Path, quarantine_dir: Path, *, now: str | None = None) -> Path:
    """Move a malformed cache out of the read path and write audit metadata."""
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target = quarantine_dir / f"{cache_path.stem}_{timestamp}{cache_path.suffix}"
    os.replace(cache_path, target)
    validation = validate_cache(target)
    metadata = {
        "format": 1,
        "quarantined_file": target.name,
        "quarantined_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_bit_count": validation.bit_count,
        "malformed_lines": list(validation.malformed_lines),
        "reason": "malformed_cache_lines",
    }
    _atomic_write(target.with_suffix(".json"), json.dumps(metadata, sort_keys=True) + "\n")
    return target


def verify_cache(cache_path: Path, manifest_path: Path | None = None) -> dict[str, object]:
    """Verify a cache read-only and return public status without its full hash."""
    manifest_path = manifest_path or manifest_path_for(cache_path)
    validation = validate_cache(cache_path)
    manifest_ok = False
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_ok = (
                manifest.get("sha256") == _sha256(cache_path)
                and manifest.get("bit_count") == validation.bit_count
                and manifest.get("line_count") == validation.valid_line_count
            )
        except (OSError, json.JSONDecodeError, TypeError):
            manifest_ok = False
    return {
        "valid": validation.valid and manifest_ok,
        "bit_count": validation.bit_count,
        "valid_line_count": validation.valid_line_count,
        "malformed_lines": len(validation.malformed_lines),
        "manifest_present": manifest_path.exists(),
        "manifest_valid": manifest_ok,
        "source": "quantum" if validation.valid and manifest_ok else "secrets_fallback",
    }