from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import backend_availability_monitor as monitor


def test_ibm_check_uses_platform_backend_api(monkeypatch):
    monkeypatch.setenv("IBM_CLOUD_API_KEY", "test-api-key")
    monkeypatch.setenv("IBM_QUANTUM_INSTANCE", "test-instance-crn")
    calls: list[dict[str, object]] = []

    class FakeService:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def backends(self, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(name="ibm_fez", num_qubits=156)]

    monkeypatch.setitem(
        sys.modules,
        "qiskit_ibm_runtime",
        SimpleNamespace(QiskitRuntimeService=FakeService),
    )
    status, latency_ms, error = monitor._check_ibm_quantum()

    assert status == "up"
    assert latency_ms is not None
    assert error == ""
    assert calls[0] == {
        "channel": "ibm_quantum_platform",
        "token": "test-api-key",
        "instance": "test-instance-crn",
    }
    assert calls[1] == {"simulator": False, "operational": True, "min_num_qubits": 8}


def test_ibm_check_is_down_when_no_operational_hardware_is_available(monkeypatch):
    monkeypatch.setenv("IBM_CLOUD_API_KEY", "test-api-key")
    monkeypatch.setenv("IBM_QUANTUM_INSTANCE", "test-instance-crn")

    class FakeService:
        def __init__(self, **kwargs):
            pass

        def backends(self, **kwargs):
            return []

    monkeypatch.setitem(
        sys.modules,
        "qiskit_ibm_runtime",
        SimpleNamespace(QiskitRuntimeService=FakeService),
    )

    status, latency_ms, error = monitor._check_ibm_quantum()

    assert status == "down"
    assert latency_ms is not None
    assert "no operational ibm quantum hardware backend" in error.lower()


def test_ibm_check_redacts_credentials_from_provider_errors(monkeypatch):
    api_key = "test-api-key-that-must-not-persist"
    instance = "test-instance-crn-that-must-not-persist"
    monkeypatch.setenv("IBM_CLOUD_API_KEY", api_key)
    monkeypatch.setenv("IBM_QUANTUM_INSTANCE", instance)

    class FakeService:
        def __init__(self, **kwargs):
            raise RuntimeError(f"failed for {api_key} at {instance}")

    monkeypatch.setitem(
        sys.modules,
        "qiskit_ibm_runtime",
        SimpleNamespace(QiskitRuntimeService=FakeService),
    )

    status, latency_ms, error = monitor._check_ibm_quantum()

    assert status == "down"
    assert latency_ms is not None
    assert api_key not in error
    assert instance not in error
    assert "[REDACTED]" in error


def test_http_get_success(monkeypatch):
    class FakeResponse:
        def read(self, n=1):
            return b""
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: FakeResponse())
    status, latency_ms, error = monitor._http_get("https://example.com", timeout=0.1)
    assert status == "up"
    assert latency_ms is not None
    assert error == ""


def test_http_get_failure(monkeypatch):
    def fake_urlopen(url, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    status, latency_ms, error = monitor._http_get("https://example.com", timeout=0.1)
    assert status == "down"
    assert latency_ms is not None
    assert "timed out" in error


def test_record_backend_health(tmp_path):
    db_path = tmp_path / "quantumpsi.db"
    os_env = {
        "QUANTUM_DB_PATH": str(db_path),
        "QUANTUM_DB_KEY": "testkey",
    }
    with patch.dict("os.environ", os_env, clear=False):
        monitor.init_db.init_db()
        conn = monitor.init_db.get_connection()
        monitor._record_backend_health(conn, "ibm_quantum", "up", 12.3, "")
        row = conn.execute("SELECT provider, status, latency_ms, error_msg FROM backend_health").fetchone()
        assert row[0] == "ibm_quantum"
        assert row[1] == "up"
        assert row[2] == 12.3
        assert row[3] == ""
        conn.close()


def test_connection_uses_runtime_database_path_override(tmp_path):
    db_path = tmp_path / "runtime.db"
    with patch.dict("os.environ", {"QUANTUM_DB_PATH": str(db_path), "QUANTUM_DB_KEY": "testkey"}, clear=False):
        conn = monitor.init_db.get_connection()
        try:
            assert Path(conn.execute("PRAGMA database_list").fetchone()[2]) == db_path
        finally:
            conn.close()
