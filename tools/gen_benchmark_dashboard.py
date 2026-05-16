#!/usr/bin/env python3
"""
⟨ψ⟩Quantum — tools/gen_benchmark_dashboard.py

DB-driven benchmark dashboard generator.

Reads from quantumpsi.db:
  - benchmarks        : Shor's v2 sim/auto runs (legacy + ongoing)
  - shors_qpu_bench   : Real QPU runs (from run_shors_bench.py)

Generates reports/benchmark_dashboard.html with:
  - Last-run timestamp
  - QPU run monthly trend table
  - Full benchmark history (hardware + simulator)

NOTE (FR-20260430-quantum-dashboard-gitignore):
  reports/benchmark_dashboard.html is NOT tracked in git. It is a generated
  artifact and must be regenerated locally from your own DB. Run this script
  after any new bench run to refresh it. CI does not generate the dashboard.

Usage
-----
    python tools/gen_benchmark_dashboard.py              # generate + open
    python tools/gen_benchmark_dashboard.py --no-open    # generate only
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = _ROOT / "reports" / "benchmark_dashboard.html"
# Add src/utils directly so `import init_db` works
sys.path.insert(0, str(_ROOT / "src" / "utils"))

# Register Brave on Windows
_BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]
for _bp in _BRAVE_PATHS:
    if os.path.isfile(_bp):
        webbrowser.register("brave", None, webbrowser.BackgroundBrowser(_bp))
        break


# ═══════════════════════════════════════════════════════════════════════════
# DB loaders
# ═══════════════════════════════════════════════════════════════════════════

def _load_qpu_runs() -> list[dict]:
    """Load rows from shors_qpu_bench (may not exist yet)."""
    try:
        import init_db
        conn = init_db.get_connection()
        # Check if table exists
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shors_qpu_bench'"
        ).fetchone()
        if not exists:
            conn.close()
            return []
        rows = conn.execute(
            "SELECT id, run_date, n_value, n_qubits, success, factor_found, "
            "qpu_seconds, backend, notes FROM shors_qpu_bench ORDER BY id DESC"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "id":           r[0],
                "run_date":     r[1] or "",
                "n_value":      r[2],
                "n_qubits":     r[3],
                "success":      bool(r[4]),
                "factor_found": r[5] or "",
                "qpu_seconds":  r[6],
                "backend":      r[7] or "",
                "notes":        r[8] or "",
            })
        return result
    except Exception as exc:
        print(f"[WARN] Could not load shors_qpu_bench: {exc}")
        return []


def _load_vqe_runs() -> list[dict]:
    """Load rows from vqe_runs (may not exist yet)."""
    try:
        import init_db
        conn = init_db.get_connection()
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vqe_runs'"
        ).fetchone()
        if not exists:
            conn.close()
            return []
        rows = conn.execute(
            "SELECT id, run_date, molecule, bond_length_ang, n_qubits, n_pauli_terms,"
            " ansatz, n_parameters, optimizer, final_energy, fci_reference, delta_ha,"
            " n_evals, wall_clock_sec, backend, timestamp"
            " FROM vqe_runs ORDER BY id DESC"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "id":             r[0],
                "run_date":       r[1] or "",
                "molecule":       r[2] or "",
                "bond_length":    r[3],
                "n_qubits":       r[4],
                "n_pauli_terms":  r[5],
                "ansatz":         r[6] or "",
                "n_parameters":   r[7],
                "optimizer":      r[8] or "",
                "final_energy":   r[9],
                "fci_reference":  r[10],
                "delta_ha":       r[11],
                "n_evals":        r[12],
                "wall_clock_sec": r[13],
                "backend":        r[14] or "",
                "timestamp":      r[15] or "",
            })
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Could not load vqe_runs: {exc}")
        return []


def _load_bench_runs() -> list[dict]:
    """Load rows from benchmarks (sim + auto runs)."""
    try:
        import init_db
        conn = init_db.get_connection()
        rows = conn.execute(
            "SELECT id, algorithm, total_time_sec, required_qubits, n_value, "
            "order_r, factor1, factor2, backend, timestamp FROM benchmarks ORDER BY id DESC"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "id":           r[0],
                "algorithm":    r[1] or "shors_v2",
                "total_time_sec": r[2],
                "required_qubits": r[3],
                "n_value":      r[4],
                "order_r":      r[5],
                "factor1":      r[6],
                "factor2":      r[7],
                "backend":      r[8] or "",
                "timestamp":    r[9] or "",
                "success":      (r[6] is not None and r[6] not in (None, "None"))
                                and (r[7] is not None and r[7] not in (None, "None")),
            })
        return result
    except Exception as exc:
        print(f"[WARN] Could not load benchmarks: {exc}")
        return []


def _load_policy_events(policy_id: str = "shors_monthly_benchmark", limit: int = 20) -> list[dict]:
    """Load benchmark policy observability events for a given policy_id."""
    try:
        import init_db

        conn = init_db.get_connection()
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='policy_events'"
        ).fetchone()
        if not exists:
            conn.close()
            return []
        rows = conn.execute(
            "SELECT event_time, policy_id, event_type, status, source, detail, next_run_at "
            "FROM policy_events "
            "WHERE policy_id=? "
            "ORDER BY id DESC LIMIT ?",
            (policy_id, limit),
        ).fetchall()
        conn.close()
        return [
            {
                "event_time": r[0] or "",
                "policy_id": r[1] or "",
                "event_type": r[2] or "",
                "status": r[3] or "",
                "source": r[4] or "",
                "detail": r[5] or "",
                "next_run_at": r[6] or "",
            }
            for r in rows
        ]
    except Exception as exc:
        print(f"[WARN] Could not load policy_events for {policy_id}: {exc}")
        return []


def _load_schedule_policy(policy_id: str = "shors_monthly_benchmark") -> dict:
    """Load execution schedule policy from config for a given policy_id."""
    config_path = _ROOT / "src" / "config" / "execution_policy.json"
    try:
        import json

        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
        schedule = data.get("schedules", {}).get(policy_id, {})
        if not schedule:
            # Fallback for missing policy
            return {
                "day": 1,
                "hour": 0,
                "minute": 0,
                "task_name": policy_id,
                "qpu_cap": 300,
                "missing": True,
            }
        return {
            "day": int(schedule.get("day_of_month", 1)),
            "hour": int(schedule.get("hour", 0)),
            "minute": int(schedule.get("minute", 0)),
            "task_name": schedule.get("task_name", policy_id),
            "qpu_cap": int(data.get("qpu_caps_seconds", {}).get(policy_id, 300)),
            "missing": False,
        }
    except Exception as exc:
        print(f"[WARN] Could not load schedule policy for {policy_id}: {exc}")
        return {
            "day": 1,
            "hour": 0,
            "minute": 0,
            "task_name": policy_id,
            "qpu_cap": 300,
            "missing": True,
        }


def _next_run_iso(day: int, hour: int, minute: int) -> str:
    """Compute next monthly benchmark run timestamp in UTC."""
    now = datetime.now(timezone.utc)
    candidate = datetime(now.year, now.month, day, hour, minute, tzinfo=timezone.utc)
    if candidate <= now:
        if now.month == 12:
            candidate = datetime(now.year + 1, 1, day, hour, minute, tzinfo=timezone.utc)
        else:
            candidate = datetime(now.year, now.month + 1, day, hour, minute, tzinfo=timezone.utc)
    return candidate.strftime("%Y-%m-%dT%H:%M:%SZ")


# ═══════════════════════════════════════════════════════════════════════════
# Cache widget data loader (FR-20260515-quantum-cache-widget)
# ═══════════════════════════════════════════════════════════════════════════

def _load_cache_widget_data() -> dict:
    """Load quantum bitstring cache fullness data for the widget.

    Returns dict with:
      current_bits      -- bit count in live cache file
      last_fill_peak    -- bit count at last fill (max JSONL remaining, or largest backup)
      pct_consumed      -- float 0-100 representing % consumed since last fill
      sparkline_points  -- list of (ts_str, remaining_int) from cache_usage.jsonl
    """
    # ── live cache bit count ──────────────────────────────────────────────
    live_path = _ROOT / "src" / "data" / "liveCache" / "ty_string_cache.txt"
    current_bits = 0
    if live_path.exists():
        text = live_path.read_text(encoding="utf-8", errors="ignore")
        current_bits = sum(1 for c in text if c in "01")

    # ── sparkline from JSONL ──────────────────────────────────────────────
    jsonl_path = _ROOT / "src" / "data" / "cache_usage.jsonl"
    sparkline_points: list[tuple[str, int]] = []
    jsonl_max = 0
    if jsonl_path.exists():
        for raw_line in jsonl_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
                ts = entry.get("ts", "")
                rem = int(entry.get("remaining", 0))
                sparkline_points.append((ts, rem))
                if rem > jsonl_max:
                    jsonl_max = rem
            except (json.JSONDecodeError, ValueError):
                continue

    # ── last fill peak ────────────────────────────────────────────────────
    # Primary: max remaining in JSONL; fallback to largest backup if JSONL empty
    last_fill_peak = jsonl_max
    if last_fill_peak == 0:
        backup_dir = _ROOT / "qbackups"
        if backup_dir.exists():
            for bk in sorted(backup_dir.glob("ty_string_cache_*.txt")):
                bk_bits = bk.stat().st_size  # each char is 1 byte; size ≈ bit count
                if bk_bits > last_fill_peak:
                    last_fill_peak = bk_bits

    # If live cache exceeds any logged peak, treat as just-filled (0% consumed)
    last_fill_peak = max(last_fill_peak, current_bits)

    pct_consumed = 0.0
    if last_fill_peak > 0 and current_bits < last_fill_peak:
        pct_consumed = (last_fill_peak - current_bits) / last_fill_peak * 100.0

    return {
        "current_bits": current_bits,
        "last_fill_peak": last_fill_peak,
        "pct_consumed": pct_consumed,
        "sparkline_points": sparkline_points,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Monthly trend helpers
# ═══════════════════════════════════════════════════════════════════════════

def _monthly_trend(qpu_runs: list[dict]) -> list[dict]:
    """Group QPU runs by YYYY-MM and compute per-month stats."""
    monthly: dict[str, list[dict]] = defaultdict(list)
    for r in qpu_runs:
        month = r["run_date"][:7] if len(r["run_date"]) >= 7 else "unknown"
        monthly[month].append(r)
    result = []
    for month in sorted(monthly.keys(), reverse=True):
        rows = monthly[month]
        successes = sum(1 for r in rows if r["success"])
        total_qpu = sum(r["qpu_seconds"] for r in rows)
        result.append({
            "month": month,
            "runs": len(rows),
            "successes": successes,
            "success_rate": f"{100 * successes / len(rows):.0f}%",
            "total_qpu_s": round(total_qpu, 1),
            "backends": ", ".join(sorted({r["backend"] for r in rows})),
        })
    return result


# ═══════════════════════════════════════════════════════════════════════════
# HTML helpers
# ═══════════════════════════════════════════════════════════════════════════

def _esc(val) -> str:
    return html.escape(str(val)) if val is not None else "&mdash;"


def _badge(success: bool, factor_found: str = "") -> str:
    if success and factor_found:
        return f'<span class="badge success">✓ {_esc(factor_found)}</span>'
    if success:
        return '<span class="badge success">SUCCESS</span>'
    return '<span class="badge fail">FAILED</span>'


def _policy_badge(status: str) -> str:
    low = (status or "").lower()
    if low in ("succeeded", "started"):
        return f'<span class="badge success">{_esc(low.upper())}</span>'
    if low in ("failed", "deferred", "manual_override"):
        return f'<span class="badge fail">{_esc(low.upper())}</span>'
    if low in ("skipped",):
        return f'<span class="badge warn">{_esc(low.upper())}</span>'
    return '<span class="badge warn">UNKNOWN</span>'


def _build_policy_panel(policy_id: str, events: list[dict], schedule_policy: dict) -> str:
    """Build schedule + event observability panel for a benchmark policy.
    
    Args:
        policy_id: Policy identifier for titles and display
        events: List of policy event records
        schedule_policy: Schedule dict with day, hour, minute, task_name, qpu_cap
    """
    # Graceful fallback if schedule is missing
    if schedule_policy.get("missing"):
        return f"""
<div class="summary-grid">
  <div class="card hw">
    <div class="label">Policy Schedule</div>
    <div class="stat" style="font-size:1.1rem">—</div>
    <h3>{_esc(schedule_policy.get('task_name', policy_id))}</h3>
    <div class="label">No schedule configured</div>
  </div>
</div>
"""

    latest = events[0] if events else {
        "event_type": "none",
        "status": "unknown",
        "event_time": "no events",
        "detail": "No benchmark policy events logged yet.",
        "next_run_at": "",
    }
    next_run = latest.get("next_run_at") or _next_run_iso(
        schedule_policy["day"],
        schedule_policy["hour"],
        schedule_policy["minute"],
    )

    alert = "Operational"
    alert_badge = '<span class="badge success">OPERATIONAL</span>'
    if latest["status"].lower() in ("failed", "deferred", "manual_override"):
        alert = "Attention Needed"
        alert_badge = '<span class="badge fail">ATTENTION</span>'
    elif latest["status"].lower() in ("skipped", "unknown"):
        alert = "Check Policy"
        alert_badge = '<span class="badge warn">CHECK</span>'

    rows = []
    for event in events[:6]:
        rows.append(
            "<tr>"
            f"<td>{_esc(event['event_time'])}</td>"
            f"<td>{_esc(event['event_type'])}</td>"
            f"<td>{_policy_badge(event['status'])}</td>"
            f"<td class='notes'>{_esc(event['detail'])}</td>"
            "</tr>"
        )
    events_table = (
        "<table class='monthly-table'><thead><tr><th>Event Time</th><th>Event</th><th>Status</th><th>Detail</th></tr></thead><tbody>"
        + ("".join(rows) if rows else "<tr><td colspan='4' class='empty'>No events yet.</td></tr>")
        + "</tbody></table>"
    )

    return f"""
<div class="summary-grid">
  <div class="card qpu">
    <div class="label">Policy Health</div>
    <div class="stat" style="font-size:1.2rem">{_policy_badge(latest['status'])}</div>
    <h3>{_esc(latest['event_type'])}</h3>
    <div class="label">{_esc(latest['event_time'])}</div>
  </div>
  <div class="card hw">
    <div class="label">Next Scheduled Run (UTC)</div>
    <div class="stat" style="font-size:1.1rem">{_esc(next_run)}</div>
    <h3>{_esc(schedule_policy['task_name'])}</h3>
    <div class="label">Day {schedule_policy['day']} @ {schedule_policy['hour']:02d}:{schedule_policy['minute']:02d}</div>
  </div>
  <div class="card sim">
    <div class="label">Alert</div>
    <div class="stat" style="font-size:1.1rem">{alert_badge}</div>
    <h3>{alert}</h3>
    <div class="label">QPU cap {schedule_policy['qpu_cap']}s</div>
  </div>
</div>
<h2 class="monthly-heading">📡 {_esc(policy_id)} — Policy Events</h2>
{events_table}
"""


def _build_sync_panel(
    policy_id: str,
    icon: str,
    title: str,
    events: list[dict],
    schedule_policy: dict,
    extra_html: str = "",
) -> str:
    """Build a biomarker-style collapsible sync-status panel for a policy."""
    latest = events[0] if events else None
    latest_status = (latest["status"] if latest else "").lower()

    if latest_status in ("succeeded", "started"):
        health_cls = "success"
        health_label = "&#10003; Healthy"
    elif latest_status in ("failed", "deferred", "manual_override"):
        health_cls = "fail"
        health_label = "&#10007; Failing"
    else:
        health_cls = "warn"
        health_label = "&#8631; Degraded"

    last_run = _esc(latest["event_time"]) if latest else "&mdash;"
    if latest and latest.get("next_run_at"):
        next_run = _esc(latest["next_run_at"])
    else:
        next_run = _esc(_next_run_iso(
            schedule_policy.get("day", 1),
            schedule_policy.get("hour", 0),
            schedule_policy.get("minute", 0),
        ))

    task_name = _esc(schedule_policy.get("task_name", policy_id))
    qpu_cap = schedule_policy.get("qpu_cap", 300)

    rows_html = ""
    for event in events[:6]:
        rows_html += (
            "<tr>"
            f"<td>{_esc(event['event_time'])}</td>"
            f"<td>{_esc(event['event_type'])}</td>"
            f"<td>{_policy_badge(event['status'])}</td>"
            f"<td class='notes'>{_esc(event['detail'])}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html = "<tr class='sync-empty-row'><td colspan='4'>No events yet.</td></tr>"

    return f"""<div class="sync-category">
  <div class="sync-category-header" onclick="this.parentElement.classList.toggle('collapsed')">
    <span class="sync-icon">{icon}</span>
    <span class="sync-name">{_esc(title)}</span>
    <span class="badge {health_cls}">{health_label}</span>
    <span class="sync-chevron">&#9660;</span>
  </div>
  <div class="sync-category-body">
    <div class="sync-pills">
      <span class="sync-pill">Last run start: <strong>{last_run}</strong></span>
      <span class="sync-pill">Next scheduled run: <strong>{next_run}</strong></span>
      <span class="sync-pill">Policy: <strong>{task_name}</strong></span>
      <span class="sync-pill">QPU cap: <strong>{_esc(str(qpu_cap))}s</strong></span>
    </div>
    <table class="sync-table">
      <thead>
        <tr><th>Event Time</th><th>Event Type</th><th>Status</th><th>Detail</th></tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    {extra_html}
  </div>
</div>"""


def _build_qpu_table(qpu_runs: list[dict]) -> str:
    if not qpu_runs:
        return "<p class='empty'>No QPU benchmark runs yet. Run <code>tools/run_shors_bench.py</code> to add data.</p>"
    lines = ['<table class="hw-table">']
    lines.append("<thead><tr>"
                 "<th>#</th><th>Date (UTC)</th><th>Backend</th>"
                 "<th>N</th><th>Qubits</th><th>QPU&nbsp;(s)</th>"
                 "<th>Result</th><th>Notes</th>"
                 "</tr></thead><tbody>")
    for i, r in enumerate(qpu_runs, 1):
        lines.append(
            f"<tr>"
            f"<td>{r['id']}</td>"
            f"<td>{_esc(r['run_date'])}</td>"
            f"<td>{_esc(r['backend'])}</td>"
            f"<td>{r['n_value']}</td>"
            f"<td>{r['n_qubits']}</td>"
            f"<td>{r['qpu_seconds']:.1f}</td>"
            f"<td>{_badge(r['success'], r['factor_found'])}</td>"
            f"<td class='notes'>{_esc(r['notes'])}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _build_monthly_table(trend: list[dict]) -> str:
    if not trend:
        return "<p class='empty'>No monthly data yet.</p>"
    lines = ['<table class="monthly-table">']
    lines.append("<thead><tr>"
                 "<th>Month</th><th>Runs</th><th>Successes</th>"
                 "<th>Success&nbsp;Rate</th><th>Total QPU (s)</th><th>Backends</th>"
                 "</tr></thead><tbody>")
    for r in trend:
        lines.append(
            f"<tr>"
            f"<td>{_esc(r['month'])}</td>"
            f"<td>{r['runs']}</td>"
            f"<td>{r['successes']}</td>"
            f"<td>{r['success_rate']}</td>"
            f"<td>{r['total_qpu_s']}</td>"
            f"<td>{_esc(r['backends'])}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _build_vqe_table(vqe_runs: list[dict]) -> str:
    if not vqe_runs:
        return ("<p class='empty'>No VQE runs yet. Run "
                "<code>python tools/bench_vqe.py</code> to add data.</p>")
    lines = ['<table class="vqe-table">']
    lines.append("<thead><tr>"
                 "<th>#</th><th>Timestamp</th><th>Molecule</th><th>R&nbsp;(Å)</th>"
                 "<th>Qubits</th><th>Pauli&nbsp;Terms</th>"
                 "<th>Ansatz</th><th>Params</th><th>Optimizer</th>"
                 "<th>E&nbsp;(Ha)</th><th>FCI&nbsp;(Ha)</th><th>Δ&nbsp;(Ha)</th>"
                 "<th>Evals</th><th>Wall&nbsp;(s)</th><th>Backend</th><th>Status</th>"
                 "</tr></thead><tbody>")
    for r in vqe_runs:
        delta = r["delta_ha"] or 0.0
        chem_acc = abs(delta) < 1.6e-3
        badge = ('<span class="badge success">CHEM&nbsp;ACC</span>' if chem_acc
                 else '<span class="badge fail">OFF</span>')
        bl = f"{r['bond_length']:.4f}" if r["bond_length"] is not None else "&mdash;"
        lines.append(
            f"<tr>"
            f"<td>{r['id']}</td>"
            f"<td>{_esc(r['timestamp'])}</td>"
            f"<td><strong>{_esc(r['molecule'])}</strong></td>"
            f"<td>{bl}</td>"
            f"<td>{r['n_qubits']}</td>"
            f"<td>{r['n_pauli_terms']}</td>"
            f"<td>{_esc(r['ansatz'])}</td>"
            f"<td>{r['n_parameters']}</td>"
            f"<td>{_esc(r['optimizer'])}</td>"
            f"<td>{r['final_energy']:.6f}</td>"
            f"<td>{r['fci_reference']:.6f}</td>"
            f"<td>{delta:.2e}</td>"
            f"<td>{r['n_evals']}</td>"
            f"<td>{r['wall_clock_sec']:.1f}</td>"
            f"<td>{_esc(r['backend'])}</td>"
            f"<td>{badge}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _build_bench_table(bench_runs: list[dict]) -> str:
    if not bench_runs:
        return "<p class='empty'>No benchmark data.</p>"
    lines = ['<table class="bench-table">']
    lines.append("<thead><tr>"
                 "<th>#</th><th>Timestamp</th><th>Algorithm</th><th>Backend</th>"
                 "<th>N</th><th>Qubits</th><th>Time&nbsp;(s)</th>"
                 "<th>Order&nbsp;r</th><th>Factors</th><th>Status</th>"
                 "</tr></thead><tbody>")
    for r in bench_runs:
        f1 = r.get("factor1")
        f2 = r.get("factor2")
        factors = f"{f1}×{f2}" if f1 and f2 and str(f1) not in ("None", "") else "&mdash;"
        success = bool(f1 and f2 and str(f1) not in ("None", ""))
        backend = r["backend"].lower()
        is_hw = not any(x in backend for x in ("aer", "sim", "fake"))
        row_cls = "hw" if is_hw else "sim"
        lines.append(
            f"<tr class='{row_cls}'>"
            f"<td>{r['id']}</td>"
            f"<td>{_esc(r['timestamp'])}</td>"
            f"<td>{_esc(r['algorithm'])}</td>"
            f"<td>{_esc(r['backend'])}</td>"
            f"<td>{r['n_value']}</td>"
            f"<td>{r['required_qubits']}</td>"
            f"<td>{r['total_time_sec']:.3f}</td>"
            f"<td>{_esc(r['order_r'])}</td>"
            f"<td>{factors}</td>"
            f"<td>{_badge(success)}</td>"
            f"</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _build_cache_widget(data: dict) -> str:
    """Build the cache fullness floating card (FR-20260515-quantum-cache-widget).

    Contains a depletion gauge (% consumed since last fill) and a sparkline
    of the drain curve sourced from cache_usage.jsonl.
    """
    current_bits = data["current_bits"]
    last_fill_peak = data["last_fill_peak"]
    pct_consumed = data["pct_consumed"]
    sparkline_points = data["sparkline_points"]

    current_mb = f"{current_bits / 1_000_000:.2f}"
    peak_mb = f"{last_fill_peak / 1_000_000:.2f}"
    gauge_width = min(100.0, max(0.0, pct_consumed))

    gauge_html = (
        f'<div class="cache-gauge-track">'
        f'<div class="cache-gauge-fill" style="width:{gauge_width:.1f}%"></div>'
        f'</div>'
        f'<div class="cache-gauge-labels">'
        f'<span>0%</span>'
        f'<span class="cache-gauge-pct">{pct_consumed:.1f}%</span>'
        f'<span>100%</span>'
        f'</div>'
    )

    sparkline_html = ""
    if len(sparkline_points) >= 2:
        # Downsample to ≤60 points for a clean inline SVG
        step = max(1, len(sparkline_points) // 60)
        sampled = sparkline_points[::step]
        vals = [p[1] for p in sampled]
        min_v = min(vals)
        max_v = max(vals)
        range_v = float(max_v - min_v) or 1.0
        n = len(sampled)
        W, H = 220, 48
        pts = " ".join(
            f"{i / (n - 1) * W:.1f},{H - (v - min_v) / range_v * H:.1f}"
            for i, (_, v) in enumerate(sampled)
        )
        # date range label from first/last timestamps
        first_day = sparkline_points[0][0][:10] if sparkline_points else ""
        last_day = sparkline_points[-1][0][:10] if sparkline_points else ""
        date_range = f"{first_day} → {last_day}" if first_day else "usage log"
        sparkline_html = (
            f'<div class="cache-sparkline-label">Drain curve ({date_range})</div>'
            f'<svg class="cache-sparkline" viewBox="0 0 {W} {H}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="#a78bfa"'
            f' stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
            f'</svg>'
        )

    return (
        f'<div class="cache-card">'
        f'<div class="cache-card-header">'
        f'<span class="cache-icon">&#128267;</span>'
        f'<span class="cache-title">Quantum Entropy Cache</span>'
        f'</div>'
        f'<div class="cache-stat-row">'
        f'<div class="cache-stat">'
        f'<div class="cache-stat-val">{current_mb}M</div>'
        f'<div class="cache-stat-label">bits remaining</div>'
        f'</div>'
        f'<div class="cache-stat">'
        f'<div class="cache-stat-val">{peak_mb}M</div>'
        f'<div class="cache-stat-label">last fill peak</div>'
        f'</div>'
        f'</div>'
        f'<div class="cache-section-label">Depletion Since Last Fill</div>'
        f'{gauge_html}'
        f'{sparkline_html}'
        f'</div>'
    )


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard renderer
# ═══════════════════════════════════════════════════════════════════════════

_CSS = """
:root {
  --hw-accent: #1a73e8;
  --qpu-accent: #a855f7;
  --sim-accent: #e8710a;
  --success: #0d904f;
  --fail: #d93025;
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: var(--bg); color: var(--text);
  padding: 2rem; max-width: 1300px; margin: 0 auto;
}
h1 { font-size: 1.8rem; margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.5rem; }
h1 .sigil { color: #a78bfa; font-size: 2rem; }
.subtitle { color: var(--muted); margin-bottom: 0.5rem; font-size: 0.9rem; }
.last-run { color: var(--muted); font-size: 0.85rem; margin-bottom: 2rem; }
.last-run .ts { color: #60a5fa; font-weight: 600; }
.summary-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem; margin-bottom: 2rem;
}
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 1.2rem; text-align: center;
}
.card.qpu  { border-top: 3px solid var(--qpu-accent); }
.card.qpu h3 { color: var(--qpu-accent); }
.card.hw   { border-top: 3px solid var(--hw-accent); }
.card.hw h3 { color: var(--hw-accent); }
.card.sim  { border-top: 3px solid var(--sim-accent); }
.card.sim h3 { color: var(--sim-accent); }
.card h3 { margin-bottom: 0.8rem; font-size: 1rem; }
.stat { font-size: 2rem; font-weight: 700; }
.label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
h2 { font-size: 1.2rem; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border); }
h2.qpu-heading { color: var(--qpu-accent); border-color: var(--qpu-accent); }
h2.hw-heading  { color: var(--hw-accent);  border-color: var(--hw-accent); }
h2.monthly-heading { color: #34d399; border-color: #34d399; }
h2.vqe-heading { color: #f472b6; border-color: #f472b6; }
.card.vqe { border-top: 3px solid #f472b6; }
.card.vqe h3 { color: #f472b6; }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { background: var(--surface); color: var(--muted); text-transform: uppercase;
     font-size: 0.75rem; letter-spacing: 0.04em; padding: 0.7rem 0.8rem; text-align: left; }
td { padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--border); }
tr.hw td { border-left: 2px solid var(--hw-accent); }
tr.sim td { border-left: 2px solid var(--sim-accent); }
.badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 9999px;
         font-size: 0.75rem; font-weight: 600; }
.badge.success { background: rgba(13,144,79,0.2); color: #34d399; }
.badge.fail    { background: rgba(217,48,37,0.2);  color: #f87171; }
.badge.warn    { background: rgba(232,113,10,0.2); color: #fdba74; }
.notes { color: var(--muted); font-size: 0.8rem; max-width: 300px; }
.hw-table, .monthly-table, .bench-table { margin-bottom: 2rem; }
.empty { color: var(--muted); font-style: italic; margin: 1rem 0 2rem; }
code { background: var(--surface); border: 1px solid var(--border);
       padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.85em; }
/* Sync panels — collapsible biomarker-style (FR-20260513) */
.sync-category {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; margin-bottom: 1.5rem; overflow: hidden;
}
.sync-category.collapsed .sync-category-body { display: none; }
.sync-category-header {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.9rem 1.2rem; cursor: pointer; user-select: none;
  border-bottom: 1px solid var(--border);
}
.sync-category-header:hover { background: rgba(255,255,255,0.03); }
.sync-icon { font-size: 1.25rem; }
.sync-name { font-size: 1rem; font-weight: 600; flex: 1; }
.sync-chevron { font-size: 0.9rem; color: var(--muted); transition: transform 0.2s ease; }
.sync-category.collapsed .sync-chevron { transform: rotate(-90deg); }
.sync-pills {
  display: flex; gap: 0.5rem; flex-wrap: wrap;
  padding: 0.9rem 1.2rem 0;
}
.sync-pill {
  background: rgba(255,255,255,0.06); border: 1px solid var(--border);
  border-radius: 9999px; padding: 0.25rem 0.75rem;
  font-size: 0.78rem; color: var(--muted);
}
.sync-pill strong { color: var(--text); }
.sync-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 0.9rem 0 0; }
.sync-table th {
  background: rgba(0,0,0,0.2); color: var(--muted); text-transform: uppercase;
  font-size: 0.75rem; letter-spacing: 0.04em; padding: 0.7rem 1.2rem; text-align: left;
}
.sync-table td { padding: 0.6rem 1.2rem; border-bottom: 1px solid var(--border); }
.sync-empty-row td { color: var(--muted); font-style: italic; text-align: center; }
/* Cache fullness widget — FR-20260515-quantum-cache-widget */
.cache-card {
  background: var(--surface); border: 1px solid var(--border);
  border-top: 3px solid #a78bfa; border-radius: 12px; padding: 1.2rem;
  margin-top: 1rem;
}
.cache-card-header {
  display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem;
}
.cache-icon { font-size: 1.2rem; }
.cache-title { font-size: 0.95rem; font-weight: 600; color: #a78bfa; }
.cache-stat-row {
  display: flex; gap: 0.5rem; justify-content: space-around; margin-bottom: 1rem;
}
.cache-stat { text-align: center; }
.cache-stat-val { font-size: 1.3rem; font-weight: 700; }
.cache-stat-label {
  color: var(--muted); font-size: 0.68rem; text-transform: uppercase;
  letter-spacing: 0.05em; margin-top: 0.15rem;
}
.cache-section-label {
  color: var(--muted); font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.05em; margin-bottom: 0.4rem;
}
.cache-gauge-track {
  background: var(--border); border-radius: 9999px;
  height: 10px; width: 100%; overflow: hidden; margin-bottom: 0.3rem;
}
.cache-gauge-fill {
  height: 100%; border-radius: 9999px;
  background: linear-gradient(90deg, #a78bfa, #7c3aed); min-width: 2px;
}
.cache-gauge-labels {
  display: flex; justify-content: space-between;
  font-size: 0.7rem; color: var(--muted); margin-bottom: 1rem;
}
.cache-gauge-pct { color: #a78bfa; font-weight: 600; }
.cache-sparkline-label {
  color: var(--muted); font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.05em; margin-bottom: 0.3rem;
}
.cache-sparkline { width: 100%; height: 50px; display: block; overflow: visible; }
"""


def generate_html(
    qpu_runs: list[dict],
    bench_runs: list[dict],
    trend: list[dict],
    generated_at: str,
    policy_events: list[dict],
    schedule_policy: dict,
    vqe_runs: list[dict] | None = None,
) -> str:
    vqe_runs = vqe_runs or []
    last_qpu = qpu_runs[0] if qpu_runs else None
    last_bench = bench_runs[0] if bench_runs else None
    last_ts = (last_qpu["run_date"] if last_qpu else
               last_bench["timestamp"] if last_bench else "never")

    qpu_total = len(qpu_runs)
    qpu_success = sum(1 for r in qpu_runs if r["success"])
    hw_runs = [r for r in bench_runs if not any(x in r["backend"].lower() for x in ("aer","sim","fake"))]
    sim_runs = [r for r in bench_runs if any(x in r["backend"].lower() for x in ("aer","sim","fake"))]
    vqe_total = len(vqe_runs)
    vqe_chem_acc = sum(1 for r in vqe_runs if r["delta_ha"] is not None and abs(r["delta_ha"]) < 1.6e-3)
    
    # Load policies for all three schedules
    shors_events = _load_policy_events("shors_monthly_benchmark")
    vqe_events = _load_policy_events("vqe_monthly_benchmark")
    vqe_schedule = _load_schedule_policy("vqe_monthly_benchmark")
    cache_fill_events = _load_policy_events("quantum_cache_fill_monthly")
    cache_fill_schedule = _load_schedule_policy("quantum_cache_fill_monthly")

    # Cache fullness widget (FR-20260515-quantum-cache-widget)
    cache_widget_data = _load_cache_widget_data()
    cache_widget = _build_cache_widget(cache_widget_data)

    shors_policy_panel = _build_sync_panel(
        "shors_monthly_benchmark", "&#128302;", "Shor's Monthly Benchmark",
        shors_events, schedule_policy,
    )
    cache_fill_panel = _build_sync_panel(
        "quantum_cache_fill_monthly", "&#128267;", "Quantum Entropy Cache Fill",
        cache_fill_events, cache_fill_schedule,
        extra_html=cache_widget,
    )
    vqe_sync_panel = _build_sync_panel(
        "vqe_monthly_benchmark", "&#129514;", "VQE Molecular Simulation",
        vqe_events, vqe_schedule,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>⟨ψ⟩Quantum — Benchmark Dashboard</title>
<style>{_CSS}</style>
</head>
<body>
<h1><span class="sigil">⟨ψ⟩</span>Quantum Benchmark Dashboard</h1>
<div class="subtitle">Shor's Algorithm — IBM Quantum QPU + Simulator Runs · VQE Molecular Simulation</div>
<div class="last-run">
  Last QPU run: <span class="ts">{_esc(last_ts)}</span>
  &nbsp;·&nbsp; Dashboard generated: <span class="ts">{_esc(generated_at)}</span>
</div>

{cache_fill_panel}

{vqe_sync_panel}

{shors_policy_panel}

<div class="summary-grid">
  <div class="card qpu">
    <div class="label">QPU Runs</div>
    <div class="stat">{qpu_total}</div>
    <h3>Real Hardware</h3>
    <div class="label">Successes</div>
    <div class="stat" style="font-size:1.4rem">{qpu_success} / {qpu_total}</div>
  </div>
  <div class="card hw">
    <div class="label">Bench (HW)</div>
    <div class="stat">{len(hw_runs)}</div>
    <h3>IBM Hardware</h3>
  </div>
  <div class="card sim">
    <div class="label">Bench (Sim)</div>
    <div class="stat">{len(sim_runs)}</div>
    <h3>Aer Simulator</h3>
  </div>
  <div class="card vqe">
    <div class="label">VQE Runs</div>
    <div class="stat">{vqe_total}</div>
    <h3>Molecular (Aer)</h3>
    <div class="label">Chem Acc</div>
    <div class="stat" style="font-size:1.4rem">{vqe_chem_acc} / {vqe_total}</div>
  </div>
</div>

<h2 class="vqe-heading">🧪 VQE — Molecular Simulation (Aer)</h2>
{_build_vqe_table(vqe_runs)}

<h2 class="qpu-heading">🔬 QPU Runs — Real IBM Quantum Hardware</h2>
{_build_qpu_table(qpu_runs)}

<h2 class="monthly-heading">📅 Monthly QPU Trend</h2>
{_build_monthly_table(trend)}

<h2 class="hw-heading">📊 Full Benchmark History (Shor's v2)</h2>
{_build_bench_table(bench_runs)}

<script>
// Auto-refresh every 60 seconds when the page is open (for live monitoring)
setTimeout(() => location.reload(), 60000);
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ⟨ψ⟩Quantum benchmark dashboard.")
    parser.add_argument("--no-open", action="store_true", help="Generate only; do not open browser.")
    args = parser.parse_args()

    qpu_runs = _load_qpu_runs()
    bench_runs = _load_bench_runs()
    vqe_runs = _load_vqe_runs()
    shors_events = _load_policy_events("shors_monthly_benchmark")
    shors_schedule = _load_schedule_policy("shors_monthly_benchmark")
    trend = _monthly_trend(qpu_runs)
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html_content = generate_html(
        qpu_runs,
        bench_runs,
        trend,
        generated_at,
        shors_events,
        shors_schedule,
        vqe_runs,
    )
    OUT_PATH.write_text(html_content, encoding="utf-8")
    print(f"Dashboard written: {OUT_PATH}")

    if not args.no_open:
        try:
            webbrowser.get("brave").open(OUT_PATH.as_uri())
        except Exception:
            webbrowser.open(OUT_PATH.as_uri())


if __name__ == "__main__":
    main()
