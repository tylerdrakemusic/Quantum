from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tomllib

import pytest

from quantum_randomness_service.app import create_app
from quantum_randomness_service.limits import RateLimiter
from quantum_randomness_service.provider import ManifestError, VerifiedCacheStore, random_bytes
from quantum_randomness_service.worker import (
    IBMQuantumProvider,
    TigrisS3Publisher,
    TIGRIS_BUCKET,
    TIGRIS_KEY,
    run_refill_once,
    publish_atomically,
    refill_needed,
    next_scheduled_run,
)


@pytest.fixture()
def client():
    app = create_app({"TESTING": True, "FLY_BEARER_TOKEN": "test-token"})
    return app.test_client()


def test_health_and_status_are_public_and_status_does_not_leak_secret(client):
    assert client.get("/health").status_code == 200
    response = client.get("/v1/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["service"] == "quantum-randomness"
    assert "test-token" not in response.get_data(as_text=True)


def test_bytes_requires_bearer_token_and_returns_requested_length(client):
    assert client.get("/v1/bytes?n=4").status_code == 401
    response = client.get(
        "/v1/bytes?n=4", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["bytes_hex"]) == 8
    assert payload["provenance"]["source"] in {"quantum", "os_csprng"}


def test_bits_integer_and_bool_endpoints_return_typed_json(client):
    headers = {"Authorization": "Bearer test-token"}
    bits = client.get("/v1/bits?n=7", headers=headers)
    bounded = client.get("/v1/ints?min=3&max=8", headers=headers)
    boolean = client.get("/v1/bool", headers=headers)
    assert bits.status_code == bounded.status_code == boolean.status_code == 200
    assert len(bits.get_json()["bits"]) == 7
    assert 3 <= bounded.get_json()["value"] <= 8
    assert isinstance(boolean.get_json()["value"], bool)


def test_request_size_limit_is_one_kibibyte(client):
    response = client.get(
        "/v1/bytes?n=1025", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 413


def test_rate_limiter_enforces_minute_and_hour_buckets():
    limiter = RateLimiter(max_per_minute=2, max_per_hour=3)
    now = datetime(2026, 9, 8, tzinfo=timezone.utc)
    assert limiter.allow("token", now)
    assert limiter.allow("token", now + timedelta(seconds=1))
    assert not limiter.allow("token", now + timedelta(seconds=2))
    assert limiter.allow("token", now + timedelta(minutes=1, seconds=1))
    assert not limiter.allow("token", now + timedelta(minutes=2))


def test_signed_manifest_verification_retains_last_verified_generation(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    manifest = store.publish(["0101"], generated_at="2026-09-08T00:00:00Z")
    assert store.load_verified().generation == manifest["generation"]
    with pytest.raises(ManifestError):
        store.accept_manifest({**manifest, "signature": "invalid"})
    assert store.load_verified().generation == manifest["generation"]


def test_api_store_refreshes_from_worker_published_manifest_and_retains_local_fallback(tmp_path):
    worker_store = VerifiedCacheStore(tmp_path / "worker", signing_key=b"signing-key")
    api_store = VerifiedCacheStore(tmp_path / "api", signing_key=b"signing-key")
    first = worker_store.publish(["0101"], generated_at="2026-09-08T00:00:00Z")
    api_store.accept_manifest(first)
    second = worker_store.build_manifest(["1111"], generated_at="2026-09-08T01:00:00Z")

    assert api_store.refresh_from_manifest(lambda: second).generation == second["generation"]
    assert api_store.load_verified().generation == second["generation"]

    assert api_store.refresh_from_manifest(lambda: (_ for _ in ()).throw(OSError("Tigris unavailable"))).generation == second["generation"]


def test_api_reads_manifest_url_without_worker_provider_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTUM_MANIFEST_SIGNING_KEY", "signing-key")
    monkeypatch.delenv("IBM_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("IBM_QUANTUM_INSTANCE", raising=False)
    app = create_app({
        "TESTING": True,
        "FLY_BEARER_TOKEN": "test-token",
        "QUANTUM_CACHE_DIR": str(tmp_path),
        "QUANTUM_MANIFEST_URL": "https://fly.storage.tigris.dev/quantum-randomness-cache/verified/generation.json",
    })
    assert app.config["QUANTUM_MANIFEST_URL"].startswith("https://")
    assert "AWS_ACCESS_KEY_ID" not in app.config
    assert "AWS_SECRET_ACCESS_KEY" not in app.config


def test_status_remains_available_when_remote_manifest_and_local_fallback_are_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("quantum_randomness_service.provider.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Tigris unavailable")))
    app = create_app({
        "TESTING": True,
        "QUANTUM_MANIFEST_SIGNING_KEY": b"signing-key",
        "QUANTUM_CACHE_DIR": str(tmp_path),
        "QUANTUM_MANIFEST_URL": "https://example.invalid/generation.json",
    })
    response = app.test_client().get("/v1/status")
    assert response.status_code == 200
    assert response.get_json()["provenance"]["quantum_cache"] == "unavailable"


def test_fly_config_uses_production_wsgi_and_worker_only_secret_contract():
    fly_config = Path("fly.toml").read_text(encoding="utf-8")
    assert "gunicorn" in fly_config
    assert "IBM_CLOUD_API_KEY" not in fly_config.split("[env]", 1)[1].split("[[mounts]]", 1)[0]
    assert "AWS_SECRET_ACCESS_KEY" not in fly_config.split("[env]", 1)[1].split("[[mounts]]", 1)[0]
    assert "worker" in fly_config


def test_api_deployment_contract_is_one_machine_with_shared_consumption_volume():
    fly_config = tomllib.loads(Path("fly.toml").read_text(encoding="utf-8"))
    policy = json.loads(Path("fly.api-policy.json").read_text(encoding="utf-8"))
    deploy_script = Path("tools/deploy_randomness_service.ps1").read_text(encoding="utf-8")
    mounts = {mount["source"]: mount["destination"] for mount in fly_config["mounts"]}

    assert policy == {
        "app": "quantum-randomness",
        "machine_count": 1,
        "shared_consumption_path": "/data/verified/consumption.sqlite3",
        "volume_source": "quantum_randomness_data",
    }
    assert mounts[policy["volume_source"]] == "/data"
    assert policy["shared_consumption_path"].startswith(mounts[policy["volume_source"]] + "/")
    assert "fly scale count 1" in deploy_script
    assert "fly deploy --config fly.toml" in deploy_script


def test_pyproject_discovers_service_package_and_declares_runtime_dependencies():
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "quantum_randomness_service*" in metadata
    assert "flask" in metadata.lower()
    assert "boto3" in metadata.lower()


def test_docker_build_context_includes_declared_project_metadata():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY README.md LICENSE ./" in dockerfile


def test_randomness_service_diagram_shows_sqlite_consumption_inside_persistent_boundary():
    diagram = Path("diagrams/quantum-randomness-service.mmd").read_text(encoding="utf-8")

    assert "consumption.sqlite3" in diagram
    assert "quantum_randomness_data" in diagram
    assert "persistent volume" in diagram.lower()


def test_stale_verified_cache_is_reported_as_stale(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(["0101"], generated_at="2026-08-01T00:00:00Z")
    status = store.status(now=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert status["source"] == "os_csprng"
    assert status["quantum_cache"] == "stale"


def test_stale_verified_cache_never_supplies_entropy_bytes(tmp_path, monkeypatch):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(["0" * 64], generated_at="2026-08-01T00:00:00Z")
    monkeypatch.setattr(
        "quantum_randomness_service.provider.datetime",
        type(
            "FrozenDateTime",
            (datetime,),
            {"now": classmethod(lambda cls, tz=None: datetime(2026, 9, 8, tzinfo=timezone.utc))},
        ),
    )
    monkeypatch.setattr("quantum_randomness_service.provider.secrets.token_bytes", lambda length: b"\xA5" * length)

    value, provenance = random_bytes(8, store)

    assert value == b"\xA5" * 8
    assert provenance == {"source": "os_csprng", "quantum_cache": "stale"}


def test_cache_io_failure_returns_csprng_bytes_with_unavailable_provenance(tmp_path, monkeypatch):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(["00000001"], generated_at="2026-09-08T00:00:00Z")
    monkeypatch.setattr(
        store,
        "consume_bytes",
        lambda length: (_ for _ in ()).throw(sqlite3.OperationalError("ledger unavailable")),
    )
    monkeypatch.setattr(
        "quantum_randomness_service.provider.secrets.token_bytes",
        lambda length: b"\xA5" * length,
    )

    value, provenance = random_bytes(1, store)

    assert value == b"\xA5"
    assert provenance == {"source": "os_csprng", "quantum_cache": "unavailable"}


def test_fresh_verified_generation_is_consumed_sequentially(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(
        ["00000001", "00000010"],
        generated_at="2026-09-08T00:00:00Z",
    )

    first, first_provenance = random_bytes(1, store)
    second, second_provenance = random_bytes(1, store)

    assert first == b"\x01"
    assert second == b"\x02"
    assert first != second
    assert first_provenance["source"] == second_provenance["source"] == "quantum"
    assert first_provenance["quantum_cache"] == second_provenance["quantum_cache"] == "current"


def test_fresh_verified_generation_coordinates_consumption_across_store_instances(tmp_path):
    publisher = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    publisher.publish(
        ["00000001", "00000010"],
        generated_at="2026-09-08T00:00:00Z",
    )
    first_worker = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    second_worker = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")

    first, first_provenance = random_bytes(1, first_worker)
    second, second_provenance = random_bytes(1, second_worker)

    assert first == b"\x01"
    assert second == b"\x02"
    assert first != second
    assert first_provenance == second_provenance == {
        "source": "quantum",
        "quantum_cache": "current",
    }


def test_worker_refills_at_or_below_twenty_five_percent():
    assert refill_needed(24, 100)
    assert refill_needed(25, 100)
    assert not refill_needed(26, 100)


def test_worker_publishes_pending_manifest_then_promotes_it():
    calls: list[tuple[str, str, str]] = []

    class Publisher:
        def put_object(self, *, bucket: str, key: str, body: bytes) -> None:
            calls.append(("put", bucket, key))

        def copy_object(self, *, bucket: str, source: str, target: str) -> None:
            calls.append(("copy", source, target))

        def delete_object(self, *, bucket: str, key: str) -> None:
            calls.append(("delete", bucket, key))

    publish_atomically(Publisher(), {"generation": "verified"})
    assert calls == [
        ("put", TIGRIS_BUCKET, f"{TIGRIS_KEY}.pending"),
        ("copy", f"{TIGRIS_KEY}.pending", TIGRIS_KEY),
        ("delete", TIGRIS_BUCKET, f"{TIGRIS_KEY}.pending"),
    ]


def test_tigris_publisher_builds_s3_client_from_worker_environment(monkeypatch):
    captured: dict[str, object] = {}

    class Client:
        def put_object(self, **kwargs):
            captured["put"] = kwargs

        def copy_object(self, **kwargs):
            captured["copy"] = kwargs

        def delete_object(self, **kwargs):
            captured["delete"] = kwargs

    def client(service, **kwargs):
        captured["service"] = service
        captured["client"] = kwargs
        return Client()

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("TIGRIS_ENDPOINT", "https://fly.storage.tigris.dev")
    publisher = TigrisS3Publisher.from_environment(client_factory=client)
    publish_atomically(publisher, {"generation": "opaque"})

    assert captured["service"] == "s3"
    assert captured["client"] == {
        "endpoint_url": "https://fly.storage.tigris.dev",
        "aws_access_key_id": "access",
        "aws_secret_access_key": "secret",
    }
    assert captured["put"]["Bucket"] == TIGRIS_BUCKET
    assert captured["copy"]["CopySource"] == {"Bucket": TIGRIS_BUCKET, "Key": f"{TIGRIS_KEY}.pending"}


def test_ibm_provider_reads_credentials_only_when_worker_runs(monkeypatch):
    monkeypatch.setenv("IBM_CLOUD_API_KEY", "worker-key")
    monkeypatch.setenv("IBM_QUANTUM_INSTANCE", "worker-instance")
    calls: dict[str, object] = {}

    class Service:
        def __init__(self, **kwargs):
            calls["service"] = kwargs

        def generate_bitstrings(self, **kwargs):
            calls["generate"] = kwargs
            return ["0101"]

    provider = IBMQuantumProvider(service_factory=Service)
    assert provider.generate(4) == ["0101"]
    assert calls["service"] == {"channel": "ibm_cloud", "token": "worker-key", "instance": "worker-instance"}


def test_run_refill_once_is_policy_gated_and_keeps_previous_generation_on_remote_failure(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    previous = store.publish(["0101"], generated_at="2026-09-08T00:00:00Z")

    class Provider:
        def generate(self, bit_count: int) -> list[str]:
            assert bit_count == 8
            return ["11110000"]

    class FailingPublisher:
        def put_object(self, **kwargs):
            raise OSError("storage unavailable")

    assert run_refill_once(
        now=datetime(2026, 9, 8, 7, tzinfo=timezone.utc),
        store=store,
        provider=Provider(),
        publisher=FailingPublisher(),
        remaining_bits=25,
        capacity_bits=100,
        scheduled_for=datetime(2026, 9, 8, 7, tzinfo=timezone.utc),
        refill_bits=8,
    ) is False
    assert store.load_verified().generation == previous["generation"]


def test_monthly_schedule_rolls_forward_in_utc():
    current = datetime(2026, 9, 8, 12, 30, tzinfo=timezone.utc)
    assert next_scheduled_run(current, day=1, hour=7, minute=0) == datetime(
        2026, 10, 1, 7, tzinfo=timezone.utc
    )