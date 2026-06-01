"""
Tests for tools/audit_policy.py — FR-20260527-execution-policy-auditor.

All tests use in-memory fixture dicts; no real files or DB are touched.
DB writes are not exercised here — persist_run() is only called from the
CLI entry point, which these unit tests do not invoke.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Import the module under test ───────────────────────────────────────────
_TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(_TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "utils"))

import audit_policy  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# Fixture helpers
# ══════════════════════════════════════════════════════════════════════════

def _compliant_policy() -> dict:
    """Minimal policy where all 4 checks pass."""
    return {
        "version": 1,
        "timezone": "UTC",
        "schedules": {
            "quantum_cache_fill_monthly": {
                "task_name": "QuantumCacheFill_Monthly",
                "day_of_month": 1,
                "hour": 1,
                "minute": 0,
            },
            "PolicyComplianceAudit_Daily": {
                "policy_id": "PolicyComplianceAudit_Daily",
                "task_name": "PolicyComplianceAudit_Daily",
                "schedule": "daily",
                "time_utc": "07:00",
                "command": "C:\\G\\python.exe tools\\audit_policy.py",
            },
        },
        "qpu_caps_seconds": {
            "quantum_cache_fill_monthly": 180,
            # PolicyComplianceAudit_Daily intentionally left out for cap-warn test,
            # but for the compliant test we add it below.
        },
    }


def _make_policy_file(policy: dict) -> Path:
    """Write a policy dict to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(policy, tmp)
    tmp.close()
    return Path(tmp.name)


def _make_backup_file(policy: dict) -> Path:
    return _make_policy_file(policy)


# ══════════════════════════════════════════════════════════════════════════
# 1. Compliant config — all 4 checks PASS
# ══════════════════════════════════════════════════════════════════════════

def test_compliant_config_all_pass(tmp_path: Path) -> None:
    policy = _compliant_policy()
    # Add cap for PolicyComplianceAudit_Daily so cap check also passes
    policy["qpu_caps_seconds"]["PolicyComplianceAudit_Daily"] = 5

    policy_file = tmp_path / "execution_policy.json"
    backup_file = tmp_path / "execution_policy_backup.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    backup_file.write_text(json.dumps(policy), encoding="utf-8")

    # Schema
    schema_findings = audit_policy.check_schema(policy)
    assert all(f["status"] == "PASS" for f in schema_findings), schema_findings

    # Linkage — audit_policy.py itself references PolicyComplianceAudit_Daily
    tools_dir = Path(audit_policy.__file__).parent
    linkage_findings = audit_policy.check_linkage(policy, tools_dir)
    assert all(f["status"] == "PASS" for f in linkage_findings), linkage_findings

    # QPU caps
    cap_findings = audit_policy.check_qpu_caps(policy)
    assert all(f["status"] == "PASS" for f in cap_findings), cap_findings

    # Backup drift — identical files
    drift_findings = audit_policy.check_backup_drift(policy_file, backup_file)
    assert all(f["status"] == "PASS" for f in drift_findings), drift_findings


# ══════════════════════════════════════════════════════════════════════════
# 2. Orphaned policy_id — linkage WARN (no consuming script)
# ══════════════════════════════════════════════════════════════════════════

def test_orphaned_policy_id_linkage_warn(tmp_path: Path) -> None:
    policy = _compliant_policy()
    policy["schedules"]["ghost_policy"] = {
        "policy_id": "ghost_policy_orphan_xyz_unique",
        "task_name": "GhostTask",
        "schedule": "daily",
        "time_utc": "08:00",
        "command": "C:\\G\\python.exe tools\\ghost.py",
    }

    # Use a temp tools_dir with no scripts to guarantee no match
    empty_tools = tmp_path / "tools"
    empty_tools.mkdir()

    findings = audit_policy.check_linkage(policy, tools_dir=empty_tools)
    warn_findings = [f for f in findings if f["status"] == "WARN"]
    assert any("ghost_policy_orphan_xyz_unique" in f["details"] for f in warn_findings), findings


# ══════════════════════════════════════════════════════════════════════════
# 3. Missing QPU cap — cap WARN
# ══════════════════════════════════════════════════════════════════════════

def test_missing_qpu_cap_warns() -> None:
    policy = _compliant_policy()
    # PolicyComplianceAudit_Daily is in schedules but NOT in qpu_caps_seconds
    assert "PolicyComplianceAudit_Daily" not in policy["qpu_caps_seconds"]

    findings = audit_policy.check_qpu_caps(policy)
    warn_findings = [f for f in findings if f["status"] == "WARN"]
    assert any("PolicyComplianceAudit_Daily" in f["details"] for f in warn_findings), findings


# ══════════════════════════════════════════════════════════════════════════
# 4. Backup drift — drift WARN when backup differs
# ══════════════════════════════════════════════════════════════════════════

def test_backup_drift_warns(tmp_path: Path) -> None:
    policy = _compliant_policy()
    backup_policy = _compliant_policy()
    backup_policy["version"] = 99  # mutate to create a drift

    policy_file = tmp_path / "execution_policy.json"
    backup_file = tmp_path / "execution_policy_backup.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    backup_file.write_text(json.dumps(backup_policy), encoding="utf-8")

    findings = audit_policy.check_backup_drift(policy_file, backup_file)
    assert any(f["status"] == "WARN" for f in findings), findings


# ══════════════════════════════════════════════════════════════════════════
# 5. Missing required schema key — monthly entry missing day_of_month → FAIL
# ══════════════════════════════════════════════════════════════════════════

def test_missing_schema_key_monthly_fails() -> None:
    policy = _compliant_policy()
    # Remove day_of_month from the monthly entry to trigger FAIL
    del policy["schedules"]["quantum_cache_fill_monthly"]["day_of_month"]

    findings = audit_policy.check_schema(policy)
    fail_findings = [f for f in findings if f["status"] == "FAIL"]
    assert fail_findings, f"Expected FAIL but got: {findings}"
    assert any(
        "quantum_cache_fill_monthly" in f["details"] for f in fail_findings
    ), fail_findings


# ══════════════════════════════════════════════════════════════════════════
# Integration: run_all_checks aggregates correctly
# ══════════════════════════════════════════════════════════════════════════

def test_run_all_checks_returns_fail_when_schema_fails(tmp_path: Path) -> None:
    policy = _compliant_policy()
    # Corrupt monthly entry — neither day_of_month nor schedule
    policy["schedules"]["bad_entry"] = {"task_name": "Broken"}

    policy_file = tmp_path / "execution_policy.json"
    backup_file = tmp_path / "execution_policy_backup.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    backup_file.write_text(json.dumps(policy), encoding="utf-8")

    empty_tools = tmp_path / "tools"
    empty_tools.mkdir()

    findings, overall = audit_policy.run_all_checks(policy, policy_file, tools_dir=empty_tools)
    assert overall == "FAIL", f"Expected FAIL, got {overall}"


def test_run_all_checks_overall_warn_when_cap_missing(tmp_path: Path) -> None:
    policy = _compliant_policy()
    # PolicyComplianceAudit_Daily missing from caps → WARN
    policy_file = tmp_path / "execution_policy.json"
    backup_file = tmp_path / "execution_policy_backup.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    backup_file.write_text(json.dumps(policy), encoding="utf-8")

    # Use actual tools dir — audit_policy.py references PolicyComplianceAudit_Daily
    tools_dir = Path(audit_policy.__file__).parent

    findings, overall = audit_policy.run_all_checks(policy, policy_file, tools_dir=tools_dir)
    assert overall == "WARN", f"Expected WARN, got {overall}"


# ══════════════════════════════════════════════════════════════════════════
# FR-20260531-quantum-6-1-preflight: optional daily keys allowed
# ══════════════════════════════════════════════════════════════════════════

def test_description_allowed_on_daily_entry() -> None:
    """'description' is an optional key on daily entries — must NOT emit WARN."""
    policy = _compliant_policy()
    policy["schedules"]["PolicyComplianceAudit_Daily"]["description"] = (
        "Daily compliance audit."
    )
    findings = audit_policy.check_schema(policy)
    assert all(f["status"] != "WARN" for f in findings), (
        f"Unexpected WARN for 'description': {findings}"
    )


def test_depletion_threshold_pct_allowed_on_daily_entry() -> None:
    """'depletion_threshold_pct' is an optional key on daily entries — must NOT emit WARN."""
    policy = _compliant_policy()
    policy["schedules"]["PolicyComplianceAudit_Daily"]["depletion_threshold_pct"] = 0.25
    findings = audit_policy.check_schema(policy)
    assert all(f["status"] != "WARN" for f in findings), (
        f"Unexpected WARN for 'depletion_threshold_pct': {findings}"
    )


def test_truly_unknown_key_on_daily_entry_warns() -> None:
    """Keys not in _DAILY_REQUIRED or _DAILY_OPTIONAL must still emit WARN."""
    policy = _compliant_policy()
    policy["schedules"]["PolicyComplianceAudit_Daily"]["totally_unknown_key_xyz"] = "oops"
    findings = audit_policy.check_schema(policy)
    warn_findings = [f for f in findings if f["status"] == "WARN"]
    assert warn_findings, f"Expected WARN for unknown key but got: {findings}"
    assert any("totally_unknown_key_xyz" in f["details"] for f in warn_findings), findings
