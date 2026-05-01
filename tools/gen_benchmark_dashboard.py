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

Usage
-----
    python tools/gen_benchmark_dashboard.py              # generate + open
    python tools/gen_benchmark_dashboard.py --no-open    # generate only
"""
from __future__ import annotations

import argparse
import html
import os
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
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
.notes { color: var(--muted); font-size: 0.8rem; max-width: 300px; }
.hw-table, .monthly-table, .bench-table { margin-bottom: 2rem; }
.empty { color: var(--muted); font-style: italic; margin: 1rem 0 2rem; }
code { background: var(--surface); border: 1px solid var(--border);
       padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.85em; }
"""


def generate_html(
    qpu_runs: list[dict],
    bench_runs: list[dict],
    trend: list[dict],
    generated_at: str,
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
<div class="subtitle">Shor's Algorithm — IBM Quantum QPU + Simulator Runs</div>
<div class="last-run">
  Last QPU run: <span class="ts">{_esc(last_ts)}</span>
  &nbsp;·&nbsp; Dashboard generated: <span class="ts">{_esc(generated_at)}</span>
</div>

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
    trend = _monthly_trend(qpu_runs)
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html_content = generate_html(qpu_runs, bench_runs, trend, generated_at, vqe_runs)
    OUT_PATH.write_text(html_content, encoding="utf-8")
    print(f"Dashboard written: {OUT_PATH}")

    if not args.no_open:
        try:
            webbrowser.get("brave").open(OUT_PATH.as_uri())
        except Exception:
            webbrowser.open(OUT_PATH.as_uri())


if __name__ == "__main__":
    main()
