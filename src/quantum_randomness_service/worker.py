from __future__ import annotations

import json
import logging
import os
import time
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .provider import VerifiedCacheStore

TIGRIS_BUCKET = "quantum-randomness-cache"
TIGRIS_KEY = "verified/generation.json"
DEFAULT_TIGRIS_ENDPOINT = "https://fly.storage.tigris.dev"
_logger = logging.getLogger("quantum_randomness_worker")


class ObjectPublisher(Protocol):
    def put_object(self, *, bucket: str, key: str, body: bytes) -> None: ...

    def copy_object(self, *, bucket: str, source: str, target: str) -> None: ...

    def delete_object(self, *, bucket: str, key: str) -> None: ...


class BitstringProvider(Protocol):
    def generate(self, bit_count: int) -> list[str]: ...


class TigrisS3Publisher:
    """Small S3-compatible adapter used only by the refill worker."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    def from_environment(cls, client_factory: Callable[..., Any] | None = None) -> "TigrisS3Publisher":
        access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        if not access_key or not secret_key:
            raise RuntimeError("Tigris S3 credentials are not configured")
        if client_factory is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("boto3 is required by the refill worker") from exc
            client_factory = boto3.client
        return cls(client_factory(
            "s3",
            endpoint_url=os.environ.get("TIGRIS_ENDPOINT", DEFAULT_TIGRIS_ENDPOINT),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        ))

    def put_object(self, *, bucket: str, key: str, body: bytes) -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=body)

    def copy_object(self, *, bucket: str, source: str, target: str) -> None:
        self.client.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": source}, Key=target)

    def delete_object(self, *, bucket: str, key: str) -> None:
        self.client.delete_object(Bucket=bucket, Key=key)


class IBMQuantumProvider:
    """Generate measured Hadamard bits using IBM Quantum credentials."""

    def __init__(self, service_factory: Callable[..., Any] | None = None) -> None:
        self.service_factory = service_factory

    def generate(self, bit_count: int) -> list[str]:
        if bit_count < 1:
            raise ValueError("bit_count must be positive")
        token = os.environ.get("IBM_CLOUD_API_KEY", "").strip()
        instance = os.environ.get("IBM_QUANTUM_INSTANCE", "").strip()
        if not token or not instance:
            raise RuntimeError("IBM Quantum worker credentials are not configured")
        if self.service_factory is None:
            try:
                from qiskit import QuantumCircuit
                from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
            except ImportError as exc:
                raise RuntimeError("IBM Quantum worker dependencies are not installed") from exc
            service_factory = QiskitRuntimeService
        else:
            QuantumCircuit = None
            SamplerV2 = None
            service_factory = self.service_factory
        service = service_factory(channel="ibm_cloud", token=token, instance=instance)
        if hasattr(service, "generate_bitstrings"):
            return service.generate_bitstrings(bit_count=bit_count)
        if QuantumCircuit is None or SamplerV2 is None:
            raise RuntimeError("injected IBM service must provide generate_bitstrings")
        qubits = min(127, max(1, bit_count))
        shots = (bit_count + qubits - 1) // qubits
        backends = service.backends(simulator=False, operational=True, min_num_qubits=qubits)
        if not backends:
            raise RuntimeError("no operational IBM Quantum backend is available")
        backend = min(backends, key=lambda item: item.status().pending_jobs)
        circuit = QuantumCircuit(qubits, qubits)
        circuit.h(range(qubits))
        circuit.measure(range(qubits), range(qubits))
        result = SamplerV2(mode=backend).run([circuit], shots=shots).result()[0]
        counts = result.data.meas.get_counts()
        values: list[str] = []
        for value, count in counts.items():
            values.extend([value.replace(" ", "")] * count)
        return values


def refill_needed(remaining_bits: int, capacity_bits: int) -> bool:
    """Return whether the cache is at or below the 25 percent refill threshold."""
    if capacity_bits <= 0 or remaining_bits < 0:
        raise ValueError("cache sizes must be non-negative and capacity must be positive")
    return remaining_bits * 4 <= capacity_bits


def publish_atomically(publisher: ObjectPublisher, manifest: dict[str, Any]) -> None:
    """Publish a signed manifest through a pending S3 object and promotion."""
    temporary_key = f"{TIGRIS_KEY}.pending"
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    publisher.put_object(bucket=TIGRIS_BUCKET, key=temporary_key, body=body)
    publisher.copy_object(bucket=TIGRIS_BUCKET, source=temporary_key, target=TIGRIS_KEY)
    publisher.delete_object(bucket=TIGRIS_BUCKET, key=temporary_key)


def run_refill_once(
    *,
    now: datetime,
    store: VerifiedCacheStore,
    provider: BitstringProvider,
    publisher: ObjectPublisher,
    remaining_bits: int,
    capacity_bits: int,
    scheduled_for: datetime,
    refill_bits: int,
) -> bool:
    """Run one scheduled refill, preserving the local generation on failure."""
    if now.astimezone(timezone.utc) < scheduled_for.astimezone(timezone.utc):
        return False
    if not refill_needed(remaining_bits, capacity_bits):
        return False
    try:
        bitstrings = provider.generate(refill_bits)
        manifest = store.build_manifest(
            bitstrings, generated_at=now.astimezone(timezone.utc).isoformat()
        )
        publish_atomically(publisher, manifest)
        store.accept_manifest(manifest)
    except Exception:
        _logger.error("quantum refill failed; retained verified generation if available")
        return False
    _logger.info("quantum refill published; bits=%d", len(manifest["bits"]))
    return True


def next_scheduled_run(now: datetime, *, day: int, hour: int, minute: int) -> datetime:
    """Return the next UTC monthly schedule occurrence."""
    current = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    candidate = current.replace(
        day=min(day, monthrange(current.year, current.month)[1]), hour=hour, minute=minute
    )
    if candidate <= current:
        year, month = (
            (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
        )
        candidate = candidate.replace(
            year=year, month=month, day=min(day, monthrange(year, month)[1])
        )
    return candidate


def run_scheduled_worker(
    *,
    store: VerifiedCacheStore,
    provider: BitstringProvider,
    publisher: ObjectPublisher,
    capacity_bits: int,
    refill_bits: int,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleeper: Callable[[float], None] = time.sleep,
    day: int = 1,
    hour: int = 7,
    minute: int = 0,
) -> None:
    """Keep a worker process alive and execute the policy-declared monthly run."""
    while True:
        scheduled = next_scheduled_run(clock(), day=day, hour=hour, minute=minute)
        delay = max((scheduled - clock().astimezone(timezone.utc)).total_seconds(), 0.0)
        sleeper(delay)
        try:
            remaining = store.remaining_bits()
        except Exception:
            remaining = 0
        try:
            run_refill_once(
                now=clock(), store=store, provider=provider, publisher=publisher,
                remaining_bits=remaining, capacity_bits=capacity_bits,
                scheduled_for=scheduled, refill_bits=refill_bits,
            )
        except Exception:
            _logger.error("quantum refill failed; retained verified generation if available")
        sleeper(60.0)
