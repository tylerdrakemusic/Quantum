from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
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
    run_scheduled_worker,
)
from tools.run_randomness_machine import api_environment, worker_environment


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


def test_openapi_contract_and_swagger_ui_are_public_and_document_protected_operations(client):
    openapi_response = client.get("/openapi.json")
    docs_response = client.get("/docs")

    assert openapi_response.status_code == 200
    assert openapi_response.content_type.startswith("application/json")
    assert docs_response.status_code == 200
    assert "swagger-ui" in docs_response.get_data(as_text=True).lower()

    contract = openapi_response.get_json()
    assert contract["openapi"] == "3.1.0"
    assert set(contract["paths"]) == {
        "/health",
        "/v1/status",
        "/v1/bytes",
        "/v1/bits",
        "/v1/ints",
        "/v1/bool",
        "/openapi.json",
        "/docs",
    }
    assert "bearerAuth" in contract["components"]["securitySchemes"]
    for path in ("/v1/bytes", "/v1/bits", "/v1/ints", "/v1/bool"):
        assert contract["paths"][path]["get"]["security"] == [{"bearerAuth": []}]
    for path in ("/health", "/v1/status", "/openapi.json", "/docs"):
        assert "security" not in contract["paths"][path]["get"]

    serialized = openapi_response.get_data(as_text=True)
    assert "FLY_BEARER_TOKEN" not in serialized
    assert "FLY_BEARER_TOKEN" not in serialized


def test_randomness_service_docs_include_operator_prerequisites_and_setup_endpoint():
    documentation = Path("docs/randomness-service.md").read_text(encoding="utf-8")

    for reference in (
        "https://fly.io/docs/",
        "https://fly.io/docs/apps/secrets/",
        "https://www.tigrisdata.com/docs/",
        "https://www.tigrisdata.com/docs/s3/",
        "https://quantum.cloud.ibm.com/docs",
        "https://quantum.cloud.ibm.com/",
    ):
        assert reference in documentation
    assert "credential rotation" in documentation.lower()
    assert "bucket" in documentation.lower()
    assert "GET /openapi.json" in documentation
    assert "GET /docs" in documentation
    assert "no runtime setup" in documentation.lower()


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


def test_ints_rejects_out_of_range_candidate_before_accepting_next_candidate(
    client, monkeypatch
):
    candidates = iter(
        [
            ((1 << 64) - 1).to_bytes(8, "big"),
            (1).to_bytes(8, "big"),
        ]
    )
    calls = []

    def fake_random_bytes(count, store):
        calls.append(count)
        return next(candidates), {"source": "test"}

    monkeypatch.setattr("quantum_randomness_service.app.random_bytes", fake_random_bytes)

    response = client.get(
        "/v1/ints?min=0&max=2", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.get_json()["value"] == 1
    assert calls == [8, 8]


def test_worker_environment_excludes_api_bearer_token_and_preserves_worker_credentials():
    environment = {
        "FLY_BEARER_TOKEN": "api-token",
        "IBM_CLOUD_API_KEY": "ibm-key",
        "IBM_QUANTUM_INSTANCE": "ibm-instance",
        "AWS_ACCESS_KEY_ID": "tigris-access",
        "AWS_SECRET_ACCESS_KEY": "tigris-secret",
        "TIGRIS_ENDPOINT": "https://fly.storage.tigris.dev",
        "QUANTUM_MANIFEST_SIGNING_KEY": "signing-key",
        "QUANTUM_CACHE_DIR": "/data/verified",
        "UNRELATED_SECRET": "must-not-pass",
    }

    worker = worker_environment(environment)

    assert "FLY_BEARER_TOKEN" not in worker
    assert "UNRELATED_SECRET" not in worker
    assert worker == {
        key: environment[key]
        for key in (
            "IBM_CLOUD_API_KEY",
            "IBM_QUANTUM_INSTANCE",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "TIGRIS_ENDPOINT",
            "QUANTUM_MANIFEST_SIGNING_KEY",
            "QUANTUM_CACHE_DIR",
        )
    }


def test_machine_environments_split_api_auth_and_verified_cache_configuration(tmp_path):
    environment = {
        "FLY_BEARER_TOKEN": "api-token",
        "IBM_CLOUD_API_KEY": "ibm-key",
        "IBM_QUANTUM_INSTANCE": "ibm-instance",
        "AWS_ACCESS_KEY_ID": "tigris-access",
        "AWS_SECRET_ACCESS_KEY": "tigris-secret",
        "TIGRIS_ENDPOINT": "https://fly.storage.tigris.dev",
        "QUANTUM_MANIFEST_SIGNING_KEY": "signing-key",
        "QUANTUM_CACHE_DIR": str(tmp_path),
        "QUANTUM_MANIFEST_URL": "https://fly.storage.tigris.dev/manifest.json",
        "QUANTUM_CACHE_CAPACITY_BITS": "4096",
        "QUANTUM_REFILL_BITS": "2048",
        "UNRELATED_SECRET": "must-not-pass",
    }

    assert api_environment(environment) == {
        "FLY_BEARER_TOKEN": "api-token",
        "QUANTUM_MANIFEST_SIGNING_KEY": "signing-key",
        "QUANTUM_CACHE_DIR": str(tmp_path),
        "QUANTUM_MANIFEST_URL": "https://fly.storage.tigris.dev/manifest.json",
    }
    assert worker_environment(environment) == {
        "IBM_CLOUD_API_KEY": "ibm-key",
        "IBM_QUANTUM_INSTANCE": "ibm-instance",
        "AWS_ACCESS_KEY_ID": "tigris-access",
        "AWS_SECRET_ACCESS_KEY": "tigris-secret",
        "TIGRIS_ENDPOINT": "https://fly.storage.tigris.dev",
        "QUANTUM_MANIFEST_SIGNING_KEY": "signing-key",
        "QUANTUM_CACHE_DIR": str(tmp_path),
        "QUANTUM_CACHE_CAPACITY_BITS": "4096",
        "QUANTUM_REFILL_BITS": "2048",
    }

    worker_store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    manifest = worker_store.publish(["0101"], generated_at="2026-09-08T00:00:00Z")
    app = create_app(api_environment(environment))
    app.config["QUANTUM_MANIFEST_URL"] = ""

    response = app.test_client().get("/v1/status")

    assert response.status_code == 200
    assert response.get_json()["provenance"] == {
        "source": "quantum",
        "quantum_cache": "current",
    }
    assert app.config["QUANTUM_CACHE_DIR"] == str(tmp_path)
    assert worker_store.load_verified().generation == manifest["generation"]


def test_bits_endpoint_accepts_documented_maximum_and_rejects_above_it(client):
    headers = {"Authorization": "Bearer test-token"}

    maximum = client.get("/v1/bits?n=8192", headers=headers)
    above_maximum = client.get("/v1/bits?n=8193", headers=headers)

    assert maximum.status_code == 200
    assert len(maximum.get_json()["bits"]) == 8192
    assert above_maximum.status_code == 413


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


def test_invalid_retained_manifest_timestamp_reports_unavailable(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    manifest = store.build_manifest(["00000001"], generated_at="not-a-timestamp")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(manifest), encoding="utf-8")

    app = create_app({
        "TESTING": True,
        "QUANTUM_MANIFEST_SIGNING_KEY": b"signing-key",
        "QUANTUM_CACHE_DIR": str(tmp_path),
    })

    response = app.test_client().get("/v1/status")

    assert response.status_code == 200
    assert response.get_json()["provenance"] == {
        "source": "os_csprng",
        "quantum_cache": "unavailable",
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("bits", [["0"]]),
        ("generation", ["generation"]),
        ("generated_at", {"date": "2026-09-08T00:00:00Z"}),
    ],
)
def test_malformed_signed_manifest_reports_unavailable_instead_of_raising(
    tmp_path, field, value
):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    manifest = store.build_manifest(["00000001"], generated_at="2026-09-08T00:00:00Z")
    manifest[field] = value
    manifest["signature"] = store._signature(manifest)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(manifest), encoding="utf-8")

    app = create_app({
        "TESTING": True,
        "QUANTUM_MANIFEST_SIGNING_KEY": b"signing-key",
        "QUANTUM_CACHE_DIR": str(tmp_path),
    })

    response = app.test_client().get("/v1/status")

    assert response.status_code == 200
    assert response.get_json()["provenance"] == {
        "source": "os_csprng",
        "quantum_cache": "unavailable",
    }


def test_fly_config_uses_production_wsgi_and_worker_only_secret_contract():
    fly_config = Path("fly.toml").read_text(encoding="utf-8")
    machine_runner = Path("tools/run_randomness_machine.py").read_text(encoding="utf-8")
    services = tomllib.loads(fly_config)["services"]
    service_ports = {port["port"]: port["handlers"] for port in services[0]["ports"]}
    assert "gunicorn" in machine_runner
    assert "IBM_CLOUD_API_KEY" not in fly_config.split("[env]", 1)[1].split("[[mounts]]", 1)[0]
    assert "AWS_SECRET_ACCESS_KEY" not in fly_config.split("[env]", 1)[1].split("[[mounts]]", 1)[0]
    assert "QUANTUM_MANIFEST_SIGNING_KEY" in fly_config
    assert "machine" in fly_config
    assert service_ports[443] == ["tls", "http"]


def test_api_deployment_contract_is_one_machine_with_shared_consumption_volume():
    fly_config = tomllib.loads(Path("fly.toml").read_text(encoding="utf-8"))
    policy = json.loads(Path("fly.api-policy.json").read_text(encoding="utf-8"))
    deploy_script = Path("tools/deploy_randomness_service.ps1").read_text(encoding="utf-8")
    mounts = {mount["source"]: mount["destination"] for mount in fly_config["mounts"]}

    assert policy["app"] == "quantum-randomness"
    assert policy["machine_count"] == 1
    assert policy["machine_process"] == "machine"
    assert policy["gunicorn_workers"] == 1
    assert policy["shared_consumption_path"] == "/data/verified/consumption.sqlite3"
    assert policy["volume_source"] == "quantum_randomness_data"
    assert mounts[policy["volume_source"]] == "/data"
    assert policy["shared_consumption_path"].startswith(mounts[policy["volume_source"]] + "/")
    assert "flyctl scale count 1 --process-group machine" in deploy_script
    assert "flyctl deploy --config fly.toml" in deploy_script
    assert "flyctl secrets import --app" in deploy_script
    assert "FLY_BEARER_TOKEN" in deploy_script
    assert "QUANTUM_MANIFEST_SIGNING_KEY" in deploy_script
    assert "FLY_API_TOKEN" not in deploy_script


def test_production_deploy_rejects_missing_bearer_secret_before_fly_call(tmp_path):
    policy = json.loads(Path("fly.api-policy.json").read_text(encoding="utf-8"))
    deploy_script = Path("tools/deploy_randomness_service.ps1")
    fly_log = tmp_path / "fly-called.txt"
    fake_fly = tmp_path / "fly.cmd"
    fake_fly.write_text(
        f"@echo called>>\"{fly_log}\"\r\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["QUANTUM_MANIFEST_SIGNING_KEY"] = "signing-key-for-test-only"
    environment.pop("FLY_BEARER_TOKEN", None)
    environment["PATH"] = str(tmp_path) + os.pathsep + environment["PATH"]

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(deploy_script)],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not fly_log.exists()
    assert "signing-key-for-test-only" not in result.stdout + result.stderr
    assert policy["required_runtime_secrets"] == [
        "FLY_BEARER_TOKEN",
        "QUANTUM_MANIFEST_SIGNING_KEY",
    ]


def test_single_fly_machine_owns_api_and_worker_with_worker_only_credentials():
    fly_config = tomllib.loads(Path("fly.toml").read_text(encoding="utf-8"))
    policy = json.loads(Path("fly.api-policy.json").read_text(encoding="utf-8"))
    machine_runner = Path("tools/run_randomness_machine.py").read_text(encoding="utf-8")
    deploy_script = Path("tools/deploy_randomness_service.ps1").read_text(encoding="utf-8")

    assert fly_config["app"] == policy["app"] == "quantum-randomness"
    assert policy["machine_count"] == 1
    assert fly_config["processes"] == {"machine": "python tools/run_randomness_machine.py"}
    assert fly_config["mounts"] == [{"source": "quantum_randomness_data", "destination": "/data"}]
    assert "IBM_CLOUD_API_KEY" in machine_runner
    assert "AWS_SECRET_ACCESS_KEY" in machine_runner
    assert "api_environment" in machine_runner
    assert "worker-only" in machine_runner.lower()
    assert "fly.worker.toml" not in deploy_script
    assert "quantum-randomness-worker" not in deploy_script


def test_rate_limit_contract_uses_one_gunicorn_worker_everywhere():
    fly_config = Path("fly.toml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    machine_runner = Path("tools/run_randomness_machine.py").read_text(encoding="utf-8")
    policy = json.loads(Path("fly.api-policy.json").read_text(encoding="utf-8"))
    docs = Path("docs/randomness-service.md").read_text(encoding="utf-8")

    assert policy["gunicorn_workers"] == 1
    assert '"--workers",\n            "1"' in machine_runner
    assert "run_randomness_machine.py" in dockerfile
    assert "one\nGunicorn worker" in docs


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


def test_exhausted_fresh_generation_reports_unavailable_csprng_provenance(tmp_path, monkeypatch):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(["00000001"], generated_at="2026-09-08T00:00:00Z")
    monkeypatch.setattr(
        "quantum_randomness_service.provider.secrets.token_bytes",
        lambda length: b"\xA5" * length,
    )

    first, first_provenance = random_bytes(1, store)
    second, second_provenance = random_bytes(1, store)

    assert first == b"\x01"
    assert first_provenance == {
        "source": "quantum",
        "quantum_cache": "current",
    }
    assert second == b"\xA5"
    assert second_provenance == {
        "source": "os_csprng",
        "quantum_cache": "unavailable",
    }


def test_worker_refills_at_or_below_twenty_five_percent():
    assert refill_needed(24, 100)
    assert refill_needed(25, 100)
    assert not refill_needed(26, 100)


def test_scheduled_worker_refills_after_shared_consumption_crosses_threshold(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(["0" * 100], generated_at="2026-09-01T00:00:00Z")
    random_bytes(10, store)

    now = [datetime(2026, 9, 1, 6, 59, tzinfo=timezone.utc)]
    provider_calls: list[int] = []
    published: list[dict[str, object]] = []

    class Provider:
        def generate(self, bit_count: int) -> list[str]:
            provider_calls.append(bit_count)
            return ["1" * bit_count]

    class Publisher:
        def put_object(self, *, bucket: str, key: str, body: bytes) -> None:
            published.append(json.loads(body))

        def copy_object(self, **kwargs) -> None:
            pass

        def delete_object(self, **kwargs) -> None:
            pass

    def clock() -> datetime:
        return now[0]

    sleep_calls = 0

    def sleeper(seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            now[0] = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
        else:
            raise RuntimeError("stop scheduled worker")

    with pytest.raises(RuntimeError, match="stop scheduled worker"):
        run_scheduled_worker(
            store=store,
            provider=Provider(),
            publisher=Publisher(),
            capacity_bits=100,
            refill_bits=16,
            clock=clock,
            sleeper=sleeper,
            day=1,
            hour=7,
            minute=0,
        )

    assert provider_calls == [16]
    assert len(published) == 1


def test_fresh_deployment_initializes_ledger_without_unconditional_scheduled_refill(tmp_path):
    store = VerifiedCacheStore(tmp_path, signing_key=b"signing-key")
    store.publish(["0" * 100], generated_at="2026-09-01T00:00:00Z")
    assert not store.consumption_path.exists()

    provider_calls: list[int] = []

    class Provider:
        def generate(self, bit_count: int) -> list[str]:
            provider_calls.append(bit_count)
            return ["1" * bit_count]

    class Publisher:
        def put_object(self, **kwargs) -> None:
            pass

        def copy_object(self, **kwargs) -> None:
            pass

        def delete_object(self, **kwargs) -> None:
            pass

    now = [datetime(2026, 9, 1, 6, 59, tzinfo=timezone.utc)]
    sleep_calls = 0

    def clock() -> datetime:
        return now[0]

    def sleeper(seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            now[0] = datetime(2026, 9, 1, 7, tzinfo=timezone.utc)
        else:
            raise RuntimeError("stop scheduled worker")

    with pytest.raises(RuntimeError, match="stop scheduled worker"):
        run_scheduled_worker(
            store=store,
            provider=Provider(),
            publisher=Publisher(),
            capacity_bits=100,
            refill_bits=16,
            clock=clock,
            sleeper=sleeper,
            day=1,
            hour=7,
            minute=0,
        )

    assert provider_calls == []
    assert store.remaining_bits() == 100
    assert store.consumption_path.exists()

    store.consume_bytes(10)
    assert store.remaining_bits() == 20
    assert run_refill_once(
        now=datetime(2026, 9, 1, 7, tzinfo=timezone.utc),
        store=store,
        provider=Provider(),
        publisher=Publisher(),
        remaining_bits=store.remaining_bits(),
        capacity_bits=100,
        scheduled_for=datetime(2026, 9, 1, 7, tzinfo=timezone.utc),
        refill_bits=16,
    )
    assert provider_calls == [16]


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