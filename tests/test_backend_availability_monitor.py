from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import backend_availability_monitor as monitor


def test_tcp_probe_success(monkeypatch):
    mock_conn = MagicMock()
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: mock_conn)
    status, latency_ms, error = monitor._tcp_probe("example.com", 443, timeout=0.1)
    assert status == "up"
    assert latency_ms is not None
    assert error == ""


def test_tcp_probe_failure(monkeypatch):
    def raise_error(*args, **kwargs):
        raise OSError("failed")

    monkeypatch.setattr("socket.create_connection", raise_error)
    status, latency_ms, error = monitor._tcp_probe("example.com", 443, timeout=0.1)
    assert status == "down"
    assert latency_ms is not None
    assert "failed" in error


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
