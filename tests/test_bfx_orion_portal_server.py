"""TDD tests for BFX-20260531-orion-prompt-edit-static.

Verifies that:
  AC1  start_quantum_benchmark.ps1 exists in ⊕Workspace/tools/
  AC2  portal_servers.json contains a port-8210 entry
  AC3  The port-8210 entry is enabled and tagged to ⟨ψ⟩Quantum project
  AC4  dashboard.json uses living_html type with serve_url pointing to :8210

Run:
    $env:PYTHONUTF8="1"
    C:\\G\\python.exe -m pytest tests/test_bfx_orion_portal_server.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — works from main checkout and git worktree
# ---------------------------------------------------------------------------
_DRIVE = Path(Path(__file__).resolve().drive + "\\")
# ⊕ = U+2295
_WORKSPACE_TOOLS: Path = _DRIVE / "\u2295Workspace" / "tools"
_QUANTUM_WORKTREE: Path = Path(__file__).resolve().parents[1]

PORTAL_SERVERS_JSON = _WORKSPACE_TOOLS / "portal_servers.json"
LAUNCHER_SCRIPT = _WORKSPACE_TOOLS / "start_quantum_benchmark.ps1"
DASHBOARD_JSON = _QUANTUM_WORKTREE / "dashboard.json"

# Tests that reference ⊕Workspace files only run locally (CI clones Quantum
# repo only; ⊕Workspace is unavailable on the runner).
_requires_workspace = pytest.mark.skipif(
    not _WORKSPACE_TOOLS.exists() or bool(os.environ.get("CI")),
    reason="⊕Workspace files not available in CI environment",
)


# ---------------------------------------------------------------------------
# AC1 — launcher script exists
# ---------------------------------------------------------------------------

@_requires_workspace
def test_launcher_script_exists() -> None:
    assert LAUNCHER_SCRIPT.exists(), (
        f"Missing launcher script: {LAUNCHER_SCRIPT}\n"
        "Create f:\\⊕Workspace\\tools\\start_quantum_benchmark.ps1"
    )


# ---------------------------------------------------------------------------
# AC2 — portal_servers.json contains a port-8210 entry
# ---------------------------------------------------------------------------

@_requires_workspace
def test_portal_servers_json_has_port_8210() -> None:
    assert PORTAL_SERVERS_JSON.exists(), f"Missing: {PORTAL_SERVERS_JSON}"
    data = json.loads(PORTAL_SERVERS_JSON.read_text(encoding="utf-8-sig"))
    ports = [s["port"] for s in data.get("servers", [])]
    assert 8210 in ports, (
        f"Port 8210 not found in portal_servers.json.\n"
        f"Current ports: {ports}"
    )


# ---------------------------------------------------------------------------
# AC3 — port-8210 entry is enabled and belongs to ⟨ψ⟩Quantum
# ---------------------------------------------------------------------------

@_requires_workspace
def test_portal_servers_quantum_entry_valid() -> None:
    data = json.loads(PORTAL_SERVERS_JSON.read_text(encoding="utf-8-sig"))
    entry = next((s for s in data["servers"] if s.get("port") == 8210), None)
    assert entry is not None, "No entry with port 8210 found"
    assert entry.get("enabled") is True, f"Port 8210 entry is not enabled: {entry}"
    # ⟨ψ⟩ = U+27E8 U+03C8 U+27E9
    assert entry.get("project") == "\u27e8\u03c8\u27e9Quantum", (
        f"Wrong project for port 8210: {entry.get('project')!r}"
    )


# ---------------------------------------------------------------------------
# AC4 — dashboard.json quantum-benchmarks entry uses living_html + serve_url
# ---------------------------------------------------------------------------

def test_dashboard_json_quantum_benchmarks_living_html() -> None:
    assert DASHBOARD_JSON.exists(), f"Missing: {DASHBOARD_JSON}"
    spec = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
    dashboards = spec.get("dashboards", [])
    entry = next((d for d in dashboards if d.get("id") == "quantum-benchmarks"), None)
    assert entry is not None, "No 'quantum-benchmarks' dashboard in dashboard.json"
    assert entry.get("type") == "living_html", (
        f"Expected type='living_html', got {entry.get('type')!r}"
    )
    serve_url = entry.get("serve_url", "")
    assert "8210" in serve_url, (
        f"serve_url should reference port 8210. Got: {serve_url!r}"
    )
