#!/usr/bin/env python3
"""⟨ψ⟩Quantum — tools/backend_availability_monitor.py

Daily IBM Quantum + Amazon Braket backend availability monitor.

This script checks the health of the two cloud providers and persists the
latest status to quantumpsi.db in the backend_health table. It is intended
for scheduled execution by src/config/execution_policy.json.
"""

from __future__ import annotations

import logging
import socket
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — allow importing from src/utils without installation
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src" / "utils"))

import init_db  # noqa: E402 — must come after sys.path insert

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POLICY_ID = "QuantumBackendAvailabilityMonitor_Daily"
_LOG = logging.getLogger("backend_availability_monitor")

# Amazon Braket public endpoint for health/status pings. Using a public status URL
# avoids requiring AWS credentials for availability detection.
_BRAKET_HOSTNAME = "status.aws.amazon.com"
_BRAKET_PATH = "/"

# IBM Quantum public endpoint for health/status pings. We use a lightweight
# TCP connect to the IBM Quantum API host to infer reachability.
_IBM_HOSTNAME = "api.quantum-computing.ibm.com"
_IBM_PORT = 443

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_backend_health(
    conn: Any,
    provider: str,
    status: str,
    latency_ms: float | None = None,
    error_msg: str = "",
) -> None:
    checked_at = _now_iso()
    conn.execute(
        """
        INSERT INTO backend_health (provider, status, latency_ms, error_msg, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (provider, status, latency_ms, error_msg, checked_at),
    )
    conn.commit()
    _LOG.info(
        "Logged backend health: provider=%s status=%s latency_ms=%s error=%s",
        provider,
        status,
        latency_ms if latency_ms is not None else "None",
        error_msg or "",
    )


def _tcp_probe(hostname: str, port: int, timeout: float = 10.0) -> tuple[str, float | None, str]:
    start = time.monotonic()
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            latency_ms = (time.monotonic() - start) * 1000.0
            return "up", latency_ms, ""
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        return "down", latency_ms, str(exc)


def _http_get(url: str, timeout: float = 10.0) -> tuple[str, float | None, str]:
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read(1)
        latency_ms = (time.monotonic() - start) * 1000.0
        return "up", latency_ms, ""
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        return "down", latency_ms, str(exc)


# ---------------------------------------------------------------------------
# Provider checks
# ---------------------------------------------------------------------------

def _check_ibm_quantum() -> tuple[str, float | None, str]:
    return _tcp_probe(_IBM_HOSTNAME, _IBM_PORT)


def _check_amazon_braket() -> tuple[str, float | None, str]:
    return _http_get(f"https://{_BRAKET_HOSTNAME}{_BRAKET_PATH}")


def _resolve_provider_label(provider: str) -> str:
    return {
        "ibm_quantum": "ibm_quantum",
        "amazon_braket": "amazon_braket",
    }.get(provider, provider)


def run_monitor() -> None:
    init_db.init_db()
    conn = init_db.get_connection()
    try:
        for provider, checker in [
            ("ibm_quantum", _check_ibm_quantum),
            ("amazon_braket", _check_amazon_braket),
        ]:
            status, latency_ms, error_msg = checker()
            _record_backend_health(
                conn,
                _resolve_provider_label(provider),
                status,
                latency_ms,
                error_msg,
            )
    finally:
        conn.close()


def main() -> None:
    try:
        run_monitor()
        sys.exit(0)
    except Exception as exc:
        _LOG.error("backend_availability_monitor.py failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
