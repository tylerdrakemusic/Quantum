from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = TEST_ROOT / "tools"
SRC_DIR = TEST_ROOT / "src"

sys.path.insert(0, str(SRC_DIR))

spec = importlib.util.spec_from_file_location(
    "bench_dashboard",
    TOOLS_DIR / "bench_dashboard.py",
)
assert spec is not None
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)  # type: ignore[union-attr]


def test_load_backend_health_reads_latest_per_provider(tmp_path):
    db_path = tmp_path / "quantumpsi.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE backend_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL,
            error_msg TEXT,
            checked_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO backend_health (provider, status, latency_ms, error_msg, checked_at) VALUES (?, ?, ?, ?, ?)",
        ("ibm_quantum", "up", 12.3, "", "2026-06-14T08:00:00Z"),
    )
    conn.execute(
        "INSERT INTO backend_health (provider, status, latency_ms, error_msg, checked_at) VALUES (?, ?, ?, ?, ?)",
        ("ibm_quantum", "down", 0.0, "timeout", "2026-06-14T09:00:00Z"),
    )
    conn.execute(
        "INSERT INTO backend_health (provider, status, latency_ms, error_msg, checked_at) VALUES (?, ?, ?, ?, ?)",
        ("amazon_braket", "up", 45.6, "", "2026-06-14T08:05:00Z"),
    )
    conn.commit()

    with patch.object(module, "get_connection", lambda: sqlite3.connect(db_path)):
        rows = module.load_backend_health()

    assert len(rows) == 2
    assert rows[0]["provider"] == "amazon_braket"
    assert rows[0]["status"] == "up"
    assert rows[1]["provider"] == "ibm_quantum"
    assert rows[1]["status"] == "down"
    conn.close()


def test_build_backend_health_section_renders_table():
    rows = [
        {
            "provider": "ibm_quantum",
            "status": "down",
            "latency_ms": 0.0,
            "error_msg": "timeout",
            "checked_at": "2026-06-14T09:00:00Z",
        },
        {
            "provider": "amazon_braket",
            "status": "up",
            "latency_ms": 45.6,
            "error_msg": "",
            "checked_at": "2026-06-14T08:05:00Z",
        },
    ]

    html = module.build_backend_health_section(rows)

    assert "Backend Availability Recommendation" in html
    assert "ibm_quantum" in html
    assert "amazon_braket" in html
    assert "DOWN" in html
    assert "UP" in html
    assert "timeout" in html
