"""
⟨ψ⟩Quantum — tools/cache_depletion_guard.py

Daily cache depletion monitor.

Reads the live cache size and the fill-completion capacity baseline, then
decides whether to trigger an early QuantumCacheFill_Monthly run.

Registered as ``QuantumCacheDepletionGuard_Daily`` in
``src/config/execution_policy.json`` with a daily schedule at 06:00 UTC.

Cooldown
--------
At most one early fill is triggered per calendar month.  If a
``fill_triggered`` event is already present in ``cache_health_log`` for the
current month the run is logged as ``fill_skipped_cooldown`` and the script
exits 0.

Usage
-----
    # Run manually:
    C:\\G\\python.exe tools\\cache_depletion_guard.py

    # Scheduled via QuantumCacheDepletionGuard_Daily Windows Task:
    C:\\G\\python.exe tools\\cache_depletion_guard.py
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow importing from src/utils without installation
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent   # f:\⟨ψ⟩Quantum\
sys.path.insert(0, str(_ROOT / "src" / "utils"))

import init_db  # noqa: E402 — must come after sys.path insert

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_LIVE_DIR         = _ROOT / "src" / "data" / "liveCache"
_LIVE_CACHE       = _LIVE_DIR / "ty_string_cache.txt"
_CAPACITY_FILE    = _LIVE_DIR / "ty_string_cache_capacity.txt"
_POLICY_FILE      = _ROOT / "src" / "config" / "execution_policy.json"
_FILL_SCRIPT      = _ROOT / "tools" / "fill_cache.py"
_POLICY_ID        = "QuantumCacheDepletionGuard_Daily"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_logger = logging.getLogger("cache_depletion_guard")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_threshold() -> float:
    """Return depletion_threshold_pct from execution_policy.json (default 0.25)."""
    try:
        policy = json.loads(_POLICY_FILE.read_text(encoding="utf-8"))
        entry = policy.get("schedules", {}).get(_POLICY_ID, {})
        return float(entry.get("depletion_threshold_pct", 0.25))
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Could not read threshold from policy file: %s — using 0.25", exc)
        return 0.25


def _count_bits(cache_path: Path) -> int:
    """Return the number of valid bit characters in the cache file."""
    total = 0
    with open(cache_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and all(c in "01" for c in stripped):
                total += len(stripped)
    return total


def _log_health(
    conn,
    bits_remaining: int,
    capacity_bits: int,
    pct_full: float,
    action_taken: str,
) -> None:
    """Insert one row into cache_health_log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO cache_health_log
            (ts, bits_remaining, capacity_bits, pct_full, action_taken)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ts, bits_remaining, capacity_bits, round(pct_full, 6), action_taken),
    )
    conn.commit()
    _logger.info(
        "Logged health: bits=%d  capacity=%d  pct=%.1f%%  action=%s",
        bits_remaining, capacity_bits, pct_full * 100, action_taken,
    )


def _cooldown_active(conn) -> bool:
    """Return True if a fill_triggered event exists for the current calendar month."""
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")   # e.g. "2026-05"
    row = conn.execute(
        """
        SELECT 1 FROM cache_health_log
        WHERE action_taken = 'fill_triggered'
          AND ts LIKE ?
        LIMIT 1
        """,
        (f"{month_prefix}%",),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Main guard logic
# ---------------------------------------------------------------------------

def run_guard() -> None:
    """Execute the depletion check and take appropriate action."""
    # ------------------------------------------------------------------
    # 1. Verify capacity baseline exists
    # ------------------------------------------------------------------
    if not _CAPACITY_FILE.exists():
        _logger.error(
            "Capacity baseline not found: %s\n"
            "Run fill_cache.py at least once to create it.",
            _CAPACITY_FILE,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Read capacity and current bits
    # ------------------------------------------------------------------
    capacity_bytes = int(_CAPACITY_FILE.read_text(encoding="utf-8").strip())
    # capacity_bytes == number of bytes in cache at fill-completion.
    # Because each bit character is one byte (ASCII 0/1), byte count ≈ bit count
    # (plus ~line-count bytes for newlines, which are negligible).
    # We use byte-count as the capacity_bits proxy for consistency with the
    # baseline write in fill_cache.py.
    capacity_bits = capacity_bytes

    if not _LIVE_CACHE.exists():
        _logger.error("Live cache not found: %s", _LIVE_CACHE)
        sys.exit(1)

    bits_remaining = _count_bits(_LIVE_CACHE)
    pct_full = bits_remaining / capacity_bits if capacity_bits > 0 else 0.0

    threshold = _load_threshold()

    _logger.info(
        "Cache status: bits_remaining=%d  capacity=%d  pct_full=%.1f%%  threshold=%.0f%%",
        bits_remaining, capacity_bits, pct_full * 100, threshold * 100,
    )

    # ------------------------------------------------------------------
    # 3. Open DB (also runs migration to ensure cache_health_log exists)
    # ------------------------------------------------------------------
    init_db.init_db()
    conn = init_db.get_connection()

    try:
        # ------------------------------------------------------------------
        # 4. Decide action
        # ------------------------------------------------------------------
        if pct_full >= threshold:
            _log_health(conn, bits_remaining, capacity_bits, pct_full, "check_ok")
            _logger.info("Cache OK — no action required.")
            return

        # Below threshold — check cooldown
        _logger.info(
            "Cache below threshold (%.1f%% < %.0f%%) — checking cooldown.",
            pct_full * 100, threshold * 100,
        )
        _log_health(conn, bits_remaining, capacity_bits, pct_full, "depletion_detected")

        if _cooldown_active(conn):
            _log_health(conn, bits_remaining, capacity_bits, pct_full, "fill_skipped_cooldown")
            _logger.info("Cooldown active — early fill already triggered this month. Skipping.")
            return

        # ------------------------------------------------------------------
        # 5. Trigger early fill
        # ------------------------------------------------------------------
        _log_health(conn, bits_remaining, capacity_bits, pct_full, "fill_triggered")
        _logger.info("Triggering early fill: %s", _FILL_SCRIPT)
        subprocess.run(
            [sys.executable, str(_FILL_SCRIPT)],
            check=True,
        )
        _logger.info("Early fill completed successfully.")

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        run_guard()
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _logger.error("cache_depletion_guard.py failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
