"""
⟨ψ⟩Quantum — tools/audit_policy.py

Standalone CLI compliance auditor for execution_policy.json.

Checks:
  1. Schema conformance  — monthly/daily entry shape validation
  2. Policy↔script linkage — each policy_id referenced in tools/*.py
  3. QPU cap coverage    — each policy_id in qpu_caps_seconds
  4. Backup drift        — SHA-256 of policy vs backup file

Usage
-----
    C:\\G\\python.exe tools\\audit_policy.py
    C:\\G\\python.exe tools\\audit_policy.py --policy-file path/to/policy.json

Exit codes:  0 = PASS or WARN,  1 = FAIL

Environment
-----------
    QUANTUM_DB_KEY   — SQLCipher key for quantumpsi.db (required for DB write)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src" / "utils"))

import init_db  # noqa: E402  (side-effect: ensures tables exist via init_db())

# ── Constants ──────────────────────────────────────────────────────────────
POLICY_ID = "PolicyComplianceAudit_Daily"

_MONTHLY_REQUIRED = {"task_name", "day_of_month", "hour", "minute"}
_DAILY_REQUIRED   = {"policy_id", "task_name", "schedule", "time_utc", "command"}

# ── Finding helpers ─────────────────────────────────────────────────────────

def _finding(check: str, status: str, details: str = "") -> dict[str, str]:
    return {"check": check, "status": status, "details": details}


# ══════════════════════════════════════════════════════════════════════════
# Individual check functions (testable — accept the policy dict directly)
# ══════════════════════════════════════════════════════════════════════════

def check_schema(policy: dict[str, Any]) -> list[dict[str, str]]:
    """Validate schema conformance for every schedule entry.

    Monthly entries (have ``day_of_month``) must contain all of
    ``_MONTHLY_REQUIRED``.  Daily entries (have ``schedule``) must contain
    all of ``_DAILY_REQUIRED``.  Entries with neither → FAIL.  Unknown keys
    beyond required set → WARN per entry.
    """
    findings: list[dict[str, str]] = []
    schedules: dict[str, Any] = policy.get("schedules", {})

    for entry_id, entry in schedules.items():
        keys = set(entry.keys())

        if "day_of_month" in entry:
            entry_type = "monthly"
            required = _MONTHLY_REQUIRED
        elif "schedule" in entry:
            entry_type = "daily"
            required = _DAILY_REQUIRED
        else:
            findings.append(_finding(
                "Schema conformance", "FAIL",
                f"{entry_id}: neither day_of_month nor schedule present",
            ))
            continue

        missing = required - keys
        if missing:
            findings.append(_finding(
                "Schema conformance", "FAIL",
                f"{entry_id} ({entry_type}): missing required keys: {sorted(missing)}",
            ))
        else:
            extra = keys - required
            if extra:
                findings.append(_finding(
                    "Schema conformance", "WARN",
                    f"{entry_id} ({entry_type}): unknown keys: {sorted(extra)}",
                ))

    if not findings:
        findings.append(_finding("Schema conformance", "PASS"))
    return findings


def check_linkage(policy: dict[str, Any], tools_dir: Path | None = None) -> list[dict[str, str]]:
    """Verify each ``policy_id`` in schedules is referenced in at least one tools/*.py file."""
    if tools_dir is None:
        tools_dir = Path(__file__).resolve().parent  # tools/ relative to this script

    findings: list[dict[str, str]] = []
    schedules: dict[str, Any] = policy.get("schedules", {})

    # Collect all tool script text once
    script_texts: list[str] = []
    for py_file in tools_dir.glob("*.py"):
        try:
            script_texts.append(py_file.read_text(encoding="utf-8"))
        except OSError:
            pass

    orphans: list[str] = []
    for entry_id, entry in schedules.items():
        pid = entry.get("policy_id", "")
        if not pid:
            # Monthly entries don't have policy_id — skip linkage check for them
            continue
        if not any(pid in text for text in script_texts):
            orphans.append(pid)

    if orphans:
        for pid in orphans:
            findings.append(_finding(
                "Policy↔script linkage", "WARN",
                f"{pid}: no consuming script found",
            ))
    else:
        findings.append(_finding("Policy↔script linkage", "PASS"))
    return findings


def check_qpu_caps(policy: dict[str, Any]) -> list[dict[str, str]]:
    """Warn for any policy_id in schedules that lacks a qpu_caps_seconds entry."""
    findings: list[dict[str, str]] = []
    schedules: dict[str, Any] = policy.get("schedules", {})
    caps: dict[str, Any] = policy.get("qpu_caps_seconds", {})

    missing_caps: list[str] = []
    for entry_id, entry in schedules.items():
        pid = entry.get("policy_id", entry_id)
        if pid not in caps:
            missing_caps.append(pid)

    if missing_caps:
        for pid in missing_caps:
            findings.append(_finding(
                "QPU cap coverage", "WARN",
                f"{pid}: missing cap",
            ))
    else:
        findings.append(_finding("QPU cap coverage", "PASS"))
    return findings


def check_backup_drift(
    policy_path: Path,
    backup_path: Path | None = None,
) -> list[dict[str, str]]:
    """Compare SHA-256 of policy file vs backup; warn if hashes differ."""
    if backup_path is None:
        backup_path = policy_path.parent / "execution_policy_backup.json"

    if not backup_path.exists():
        return [_finding("Backup drift", "WARN", "backup file not found")]

    def _sha256(p: Path) -> str:
        h = hashlib.sha256()
        h.update(p.read_bytes())
        return h.hexdigest()

    hash_policy = _sha256(policy_path)
    hash_backup = _sha256(backup_path)

    if hash_policy == hash_backup:
        return [_finding("Backup drift", "PASS")]

    # Find first differing top-level key for context
    try:
        with open(policy_path, encoding="utf-8") as f:
            cur = json.load(f)
        with open(backup_path, encoding="utf-8") as f:
            bak = json.load(f)
        diff_keys = [k for k in set(cur) | set(bak) if cur.get(k) != bak.get(k)]
        detail = f"first differing key: {diff_keys[0]}" if diff_keys else "content differs"
    except Exception:
        detail = "content differs"

    return [_finding("Backup drift", "WARN", detail)]


# ══════════════════════════════════════════════════════════════════════════
# Aggregation + persistence
# ══════════════════════════════════════════════════════════════════════════

def run_all_checks(
    policy: dict[str, Any],
    policy_path: Path,
    tools_dir: Path | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Run all 4 checks and return (findings, overall_status)."""
    all_findings: list[dict[str, str]] = []
    all_findings.extend(check_schema(policy))
    all_findings.extend(check_linkage(policy, tools_dir))
    all_findings.extend(check_qpu_caps(policy))
    all_findings.extend(check_backup_drift(policy_path))

    statuses = {f["status"] for f in all_findings}
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"

    return all_findings, overall


def _policy_file_hash(policy_path: Path) -> str:
    h = hashlib.sha256()
    h.update(policy_path.read_bytes())
    return h.hexdigest()


def persist_run(
    run_ts: str,
    status: str,
    findings: list[dict[str, str]],
    policy_file_hash: str,
) -> None:
    """Write one row to policy_audit_runs in quantum.db."""
    try:
        init_db.init_db()
        conn = init_db.get_connection()
        conn.execute(
            """
            INSERT INTO policy_audit_runs (run_ts, status, findings, policy_file_hash)
            VALUES (?, ?, ?, ?)
            """,
            (run_ts, status, json.dumps(findings), policy_file_hash),
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        # DB write failure must not block the audit from completing
        print(f"  [DB WARN] Could not persist audit run: {exc}", file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════════
# Console rendering
# ══════════════════════════════════════════════════════════════════════════

_W_CHECK   = 30
_W_STATUS  = 8
_W_DETAILS = 50
_LINE      = "═" * 55
_SEP       = "─" * 53


def _render(findings: list[dict[str, str]], overall: str, run_ts: str) -> None:
    date_str = run_ts[:10]
    print(f"\n{_LINE}")
    print(f" execution_policy.json Compliance Audit — {date_str}")
    print(_LINE)
    print(f" {'CHECK':<{_W_CHECK}} {'STATUS':<{_W_STATUS}} DETAILS")
    print(f" {_SEP}")

    for f in findings:
        check   = f["check"][:_W_CHECK]
        status  = f["status"]
        details = f.get("details", "")
        print(f" {check:<{_W_CHECK}} {status:<{_W_STATUS}} {details}")

    print(_LINE)

    warns  = sum(1 for f in findings if f["status"] == "WARN")
    fails  = sum(1 for f in findings if f["status"] == "FAIL")
    print(f" Overall: {overall}  ({warns} warning{'s' if warns != 1 else ''}, {fails} failure{'s' if fails != 1 else ''})")
    print(_LINE + "\n")


# ══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compliance auditor for execution_policy.json",
    )
    parser.add_argument(
        "--policy-file",
        default=str(_ROOT / "src" / "config" / "execution_policy.json"),
        help="Path to execution_policy.json (default: src/config/execution_policy.json)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip writing results to quantum.db",
    )
    args = parser.parse_args(argv)

    policy_path = Path(args.policy_file).resolve()
    if not policy_path.exists():
        print(f"ERROR: policy file not found: {policy_path}", file=sys.stderr)
        return 1

    with open(policy_path, encoding="utf-8") as fh:
        policy = json.load(fh)

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings, overall = run_all_checks(policy, policy_path)
    _render(findings, overall, run_ts)

    if not args.no_db:
        file_hash = _policy_file_hash(policy_path)
        persist_run(run_ts, overall, findings, file_hash)

    return 0 if overall in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
