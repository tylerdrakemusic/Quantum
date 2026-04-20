#!/usr/bin/env python3
"""
Shor's Algorithm v2 — Benchmark Dashboard (non-interactive)

Reads benchmark data from quantumpsi.db (SQLCipher encrypted) and renders
a static HTML dashboard. Hardware and simulator results are visually
separated into distinct sections.

Usage:
  python tools/bench_dashboard.py              # generate + open in browser
  python tools/bench_dashboard.py --no-open    # generate only
"""

import argparse
import html
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = PROJECT_ROOT / "reports" / "benchmark_dashboard.html"

# Register Brave on Windows (not known to webbrowser by default)
_BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]
for _bp in _BRAVE_PATHS:
    if os.path.isfile(_bp):
        webbrowser.register("brave", None, webbrowser.BackgroundBrowser(_bp))
        break

# DB access
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def load_from_db() -> list[dict]:
    """Load benchmark rows from the encrypted quantumpsi.db."""
    from utils.init_db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT total_time_sec, required_qubits, n_value, order_r, "
        "factor1, factor2, backend, timestamp FROM benchmarks ORDER BY id"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "total_time_sec": str(r[0]),
            "required_qubits": str(r[1]),
            "N": str(r[2]),
            "order_r": str(r[3]) if r[3] is not None else "",
            "factor1": str(r[4]) if r[4] is not None else "",
            "factor2": str(r[5]) if r[5] is not None else "",
            "backend": r[6] or "",
            "timestamp": r[7] or "",
        })
    return result

def classify_backend(backend: str) -> str:
    """Classify a backend string into 'hardware' or 'simulator'."""
    if not backend:
        return "hardware"  # legacy rows were IBM QPU
    low = backend.lower()
    if "aer" in low or "sim" in low or "fake" in low:
        return "simulator"
    return "hardware"


def _esc(val: str) -> str:
    return html.escape(val) if val else "&mdash;"


def _status_badge(order_r: str, f1: str, f2: str) -> str:
    if f1 and f2 and f1 not in ("", "None") and f2 not in ("", "None"):
        return '<span class="badge success">SUCCESS</span>'
    if order_r == "-1" or not order_r:
        return '<span class="badge fail">FAILED</span>'
    return '<span class="badge partial">PARTIAL</span>'


def build_table(rows: list[dict], section_class: str) -> str:
    """Build an HTML table from rows."""
    if not rows:
        return "<p class='empty'>No benchmark data.</p>"

    lines = []
    lines.append(f'<table class="{section_class}">')
    lines.append("<thead><tr>")
    lines.append("<th>#</th><th>Timestamp</th><th>Backend</th><th>N</th>")
    lines.append("<th>Qubits</th><th>Time (s)</th><th>Order r</th>")
    lines.append("<th>Factors</th><th>Status</th>")
    lines.append("</tr></thead><tbody>")

    for i, r in enumerate(rows, 1):
        ts = r.get("timestamp", "")
        ts_display = ts if ts else "unknown (pre-schema)"
        backend = r.get("backend", "")
        backend_display = backend if backend else "ibm_quantum (legacy)"
        f1, f2 = r.get("factor1", ""), r.get("factor2", "")
        factors = f"{f1} × {f2}" if f1 and f2 else "&mdash;"
        time_val = r.get("total_time_sec", "")
        badge = _status_badge(r.get("order_r", ""), f1, f2)

        lines.append("<tr>")
        lines.append(f"<td>{i}</td>")
        lines.append(f"<td class='ts'>{_esc(ts_display)}</td>")
        lines.append(f"<td>{_esc(backend_display)}</td>")
        lines.append(f"<td>{_esc(r.get('N', ''))}</td>")
        lines.append(f"<td>{_esc(r.get('required_qubits', ''))}</td>")
        lines.append(f"<td class='num'>{_esc(time_val)}</td>")
        lines.append(f"<td>{_esc(r.get('order_r', ''))}</td>")
        lines.append(f"<td>{factors}</td>")
        lines.append(f"<td>{badge}</td>")
        lines.append("</tr>")

    lines.append("</tbody></table>")
    return "\n".join(lines)


def build_summary(hw_rows: list[dict], sim_rows: list[dict]) -> str:
    """Build summary stats cards."""
    def stats(rows: list[dict]) -> dict:
        total = len(rows)
        successes = sum(1 for r in rows if r.get("factor1") and r.get("factor2"))
        times = [float(r["total_time_sec"]) for r in rows if r.get("total_time_sec")]
        avg_time = sum(times) / len(times) if times else 0
        return {"total": total, "successes": successes, "avg_time": avg_time}

    hw = stats(hw_rows)
    sim = stats(sim_rows)

    return f"""
    <div class="summary-grid">
      <div class="card hw-card">
        <h3>IBM Quantum Hardware</h3>
        <div class="stat">{hw['total']}</div><div class="label">Total Runs</div>
        <div class="stat">{hw['successes']}/{hw['total']}</div><div class="label">Successful</div>
        <div class="stat">{hw['avg_time']:.1f}s</div><div class="label">Avg Time</div>
      </div>
      <div class="card sim-card">
        <h3>Aer Simulator</h3>
        <div class="stat">{sim['total']}</div><div class="label">Total Runs</div>
        <div class="stat">{sim['successes']}/{sim['total']}</div><div class="label">Successful</div>
        <div class="stat">{sim['avg_time']:.1f}s</div><div class="label">Avg Time</div>
      </div>
    </div>
    """


def render_html(hw_rows: list[dict], sim_rows: list[dict], source: str = "quantumpsi.db") -> str:
    """Render the full HTML dashboard."""
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = build_summary(hw_rows, sim_rows)
    hw_table = build_table(hw_rows, "hw-table")
    sim_table = build_table(sim_rows, "sim-table")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Shor's v2 Benchmark Dashboard</title>
<style>
  :root {{
    --hw-accent: #1a73e8;
    --sim-accent: #e8710a;
    --success: #0d904f;
    --fail: #d93025;
    --partial: #f9ab00;
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.8rem;
    margin-bottom: 0.3rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }}
  h1 .sigil {{ color: #a78bfa; font-size: 2rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 2rem; font-size: 0.9rem; }}
  .summary-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-bottom: 2.5rem;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    text-align: center;
  }}
  .card h3 {{
    margin-bottom: 1rem;
    font-size: 1.1rem;
  }}
  .hw-card {{ border-top: 3px solid var(--hw-accent); }}
  .hw-card h3 {{ color: var(--hw-accent); }}
  .sim-card {{ border-top: 3px solid var(--sim-accent); }}
  .sim-card h3 {{ color: var(--sim-accent); }}
  .stat {{
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.2;
  }}
  .label {{
    color: var(--muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.8rem;
  }}
  h2 {{
    font-size: 1.3rem;
    margin: 2rem 0 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid var(--border);
  }}
  h2.hw-heading {{ color: var(--hw-accent); border-color: var(--hw-accent); }}
  h2.sim-heading {{ color: var(--sim-accent); border-color: var(--sim-accent); }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    margin-bottom: 2rem;
  }}
  thead {{ background: var(--surface); }}
  th {{
    text-align: left;
    padding: 0.6rem 0.8rem;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    border-bottom: 2px solid var(--border);
  }}
  td {{
    padding: 0.6rem 0.8rem;
    border-bottom: 1px solid var(--border);
  }}
  tr:hover {{ background: rgba(255,255,255,0.03); }}
  .num {{ font-variant-numeric: tabular-nums; text-align: right; }}
  .ts {{ color: var(--muted); font-size: 0.85rem; }}
  .badge {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  .badge.success {{ background: rgba(13,144,79,0.15); color: var(--success); }}
  .badge.fail {{ background: rgba(217,48,37,0.15); color: var(--fail); }}
  .badge.partial {{ background: rgba(249,171,0,0.15); color: var(--partial); }}
  .empty {{ color: var(--muted); font-style: italic; padding: 1rem; }}
  .footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 0.8rem;
    text-align: center;
  }}
</style>
</head>
<body>
  <h1><span class="sigil">&lang;&psi;&rang;</span> Shor's v2 Benchmark Dashboard</h1>
  <div class="subtitle">
    Generated: {generated} &bull; Source: {html.escape(source)}
  </div>

  {summary}

  <h2 class="hw-heading">IBM Quantum Hardware</h2>
  {hw_table}

  <h2 class="sim-heading">Aer Simulator (Local)</h2>
  {sim_table}

  <div class="footer">
    &lang;&psi;&rang;Quantum &mdash; Benchmark Dashboard &bull; Non-interactive static report
  </div>
</body>
</html>"""


def main(open_browser: bool = True) -> None:
    rows = load_from_db()
    source = "quantumpsi.db"
    print(f"  Data source: {source} ({len(rows)} rows)")

    hw_rows = [r for r in rows if classify_backend(r.get("backend", "")) == "hardware"]
    sim_rows = [r for r in rows if classify_backend(r.get("backend", "")) == "simulator"]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html_content = render_html(hw_rows, sim_rows, source=source)
    OUT_PATH.write_text(html_content, encoding="utf-8")
    print(f"Dashboard written to {OUT_PATH}")

    if open_browser:
        url = OUT_PATH.as_uri()
        opened = False
        for name in ("brave", "chrome", "firefox"):
            try:
                webbrowser.get(name).open(url)
                print(f"Opened in {name}.")
                opened = True
                break
            except webbrowser.Error:
                continue
        if not opened:
            webbrowser.open(url)
            print("Opened in default browser.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shor's v2 benchmark dashboard")
    parser.add_argument("--no-open", action="store_true", help="Don't open in browser")
    args = parser.parse_args()
    main(open_browser=not args.no_open)
