from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen


class ManifestError(ValueError):
    """Raised when a cache manifest cannot be verified."""


@dataclass(frozen=True)
class VerifiedGeneration:
    generation: str
    bits: str
    generated_at: datetime


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class VerifiedCacheStore:
    """Persist and verify one retained quantum cache generation."""

    def __init__(self, directory: Path, signing_key: bytes, max_age_days: int = 30) -> None:
        self.directory = Path(directory)
        self.signing_key = signing_key
        self.max_age = timedelta(days=max_age_days)
        self.path = self.directory / "verified-generation.json"
        self.consumption_path = self.directory / "consumption.sqlite3"
        self._consumption_lock = threading.RLock()

    def _signature(self, manifest: dict[str, Any]) -> str:
        unsigned = {key: value for key, value in manifest.items() if key != "signature"}
        payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(hmac.new(self.signing_key, payload, hashlib.sha256).digest()).decode()

    def publish(self, bitstrings: list[str], generated_at: str | None = None) -> dict[str, Any]:
        manifest = self.build_manifest(bitstrings, generated_at=generated_at)
        self.accept_manifest(manifest)
        return manifest

    def build_manifest(self, bitstrings: list[str], generated_at: str | None = None) -> dict[str, Any]:
        """Build a signed generation without replacing the retained generation."""
        if not bitstrings or any(not value or set(value) - {"0", "1"} for value in bitstrings):
            raise ValueError("replacement data must contain non-empty binary strings")
        generated = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        bits = "".join(bitstrings)
        manifest: dict[str, Any] = {
            "generation": secrets.token_hex(16),
            "bits": bits,
            "generated_at": generated,
        }
        manifest["signature"] = self._signature(manifest)
        return manifest

    def accept_manifest(self, manifest: dict[str, Any]) -> None:
        with self._consumption_lock:
            self._validate_manifest(manifest)
            self.directory.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".verified-", dir=self.directory)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(manifest, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            except BaseException:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                raise

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        if not isinstance(manifest, dict):
            raise ManifestError("manifest structure invalid")
        if not isinstance(manifest.get("generation"), str):
            raise ManifestError("manifest generation invalid")
        if not isinstance(manifest.get("bits"), str):
            raise ManifestError("manifest bits invalid")
        if not isinstance(manifest.get("generated_at"), str):
            raise ManifestError("manifest timestamp invalid")
        if not hmac.compare_digest(str(manifest.get("signature", "")), self._signature(manifest)):
            raise ManifestError("manifest signature invalid")
        if not manifest.get("generation") or not manifest.get("bits") or set(manifest["bits"]) - {"0", "1"}:
            raise ManifestError("manifest content invalid")
        try:
            _parse_time(str(manifest["generated_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError("manifest timestamp invalid") from exc

    def load_verified(self) -> VerifiedGeneration:
        try:
            manifest = json.loads(self.path.read_text(encoding="utf-8"))
            self._validate_manifest(manifest)
        except (OSError, json.JSONDecodeError, ManifestError) as exc:
            raise ManifestError("no verified generation available") from exc
        return VerifiedGeneration(
            generation=manifest["generation"],
            bits=manifest["bits"],
            generated_at=_parse_time(manifest["generated_at"]),
        )

    def refresh_from_manifest(self, fetcher: Callable[[], dict[str, Any]]) -> VerifiedGeneration:
        """Accept a verified remote generation, retaining local data on failure."""
        try:
            manifest = fetcher()
            self.accept_manifest(manifest)
        except Exception:
            return self.load_verified()
        return self.load_verified()

    def refresh_from_url(self, url: str, timeout: float = 5.0) -> VerifiedGeneration:
        """Fetch and verify the worker-published manifest from its public object URL."""
        def fetch() -> dict[str, Any]:
            with urlopen(url, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        return self.refresh_from_manifest(fetch)

    def status(self, now: datetime | None = None) -> dict[str, str]:
        try:
            generation = self.load_verified()
        except ManifestError:
            return {"source": "os_csprng", "quantum_cache": "unavailable"}
        current = now or datetime.now(timezone.utc)
        fresh = current - generation.generated_at <= self.max_age
        return {
            "source": "quantum" if fresh else "os_csprng",
            "quantum_cache": "current" if fresh else "stale",
        }

    def remaining_bits(self) -> int:
        """Return unreserved bits in the verified generation."""
        with self._consumption_lock:
            generation = self.load_verified()
            self.directory.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.consumption_path, timeout=30.0) as connection:
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS consumption "
                    "(generation TEXT PRIMARY KEY, offset INTEGER NOT NULL)"
                )
                row = connection.execute(
                    "SELECT offset FROM consumption WHERE generation = ?",
                    (generation.generation,),
                ).fetchone()
            offset = int(row[0]) if row else 0
            return max(0, len(generation.bits) - offset)

    def consume_bytes(self, length: int) -> tuple[bytes, dict[str, str]] | None:
        """Consume the next bytes from the current fresh generation safely."""
        if length < 1:
            raise ValueError("length must be positive")
        with self._consumption_lock:
            generation = self.load_verified()
            current = datetime.now(timezone.utc)
            fresh = current - generation.generated_at <= self.max_age
            provenance = {
                "source": "quantum" if fresh else "os_csprng",
                "quantum_cache": "current" if fresh else "stale",
            }
            if not fresh:
                return None
            needed = length * 8
            self.directory.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.consumption_path, timeout=30.0) as connection:
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS consumption "
                    "(generation TEXT PRIMARY KEY, offset INTEGER NOT NULL)"
                )
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT offset FROM consumption WHERE generation = ?",
                    (generation.generation,),
                ).fetchone()
                offset = int(row[0]) if row else 0
                end = offset + needed
                if end > len(generation.bits):
                    connection.rollback()
                    return None
                connection.execute(
                    "INSERT INTO consumption(generation, offset) VALUES (?, ?) "
                    "ON CONFLICT(generation) DO UPDATE SET offset = excluded.offset",
                    (generation.generation, end),
                )
                connection.commit()
            bits = generation.bits[offset:end]
            return int(bits, 2).to_bytes(length, "big"), provenance


def random_bytes(length: int, store: VerifiedCacheStore | None = None) -> tuple[bytes, dict[str, str]]:
    if store is not None:
        try:
            consumed = store.consume_bytes(length)
            if consumed is not None:
                return consumed
        except (ManifestError, OSError, sqlite3.Error):
            return secrets.token_bytes(length), {"source": "os_csprng", "quantum_cache": "unavailable"}
        provenance = store.status()
        if provenance == {"source": "quantum", "quantum_cache": "current"}:
            provenance = {"source": "os_csprng", "quantum_cache": "unavailable"}
        return secrets.token_bytes(length), provenance
    return secrets.token_bytes(length), {"source": "os_csprng", "quantum_cache": "unavailable"}
