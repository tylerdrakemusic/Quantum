"""Helper for reading and updating Orion's portrait prompts from orion_config.db.

Provides two public functions:
    get_active_prompt(mode)    -> (positive_prompt, negative_prompt | None)
    update_active_prompt(mode, positive_prompt) -> None

The DB is created by tools/seed_orion_config.py.  This module is import-safe
even if the DB does not yet exist — callers should catch RuntimeError.

Orion has three run-state prompt modes:
    'idle'         — no successful run in last 7 days
    'active'       — last successful run 1–7 days ago
    'result_ready' — last successful run within 24 hours
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH: Path = Path(__file__).resolve().parents[2] / "src" / "data" / "orion_config.db"

_VALID_MODES = ("idle", "active", "result_ready")


def _connect() -> sqlite3.Connection:
    """Open a connection to orion_config.db (open/close per call for thread safety)."""
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_prompt(mode: str = "idle") -> tuple[str, str | None]:
    """Return (positive_prompt, negative_prompt) for the given run-state mode.

    Parameters
    ----------
    mode:
        One of 'idle', 'active', or 'result_ready'.

    Returns
    -------
    tuple[str, str | None]
        (positive_prompt, negative_prompt).  ``negative_prompt`` may be None.

    Raises
    ------
    RuntimeError
        If the DB does not exist or no active row is present for the given mode.
    """
    if mode not in _VALID_MODES:
        mode = "idle"
    if not _DB_PATH.exists():
        raise RuntimeError(
            f"orion_config.db not found at {_DB_PATH}. "
            "Run tools/seed_orion_config.py to initialise."
        )
    with _connect() as conn:
        row = conn.execute(
            "SELECT positive_prompt, negative_prompt "
            "FROM orion_config WHERE mode = ? AND active = 1 ORDER BY id DESC LIMIT 1",
            (mode,),
        ).fetchone()
    if row is None:
        raise RuntimeError(
            f"No active prompt row found in orion_config.db for mode={mode!r}"
        )
    return str(row["positive_prompt"]), (row["negative_prompt"] or None)


def update_active_prompt(mode: str, positive_prompt: str) -> None:
    """Update the active row's positive_prompt for the given mode.

    Parameters
    ----------
    mode:
        One of 'idle', 'active', or 'result_ready'.
    positive_prompt:
        The new positive prompt text to store.

    Raises
    ------
    RuntimeError
        If the DB does not exist.
    """
    if mode not in _VALID_MODES:
        mode = "idle"
    if not _DB_PATH.exists():
        raise RuntimeError(
            f"orion_config.db not found at {_DB_PATH}. "
            "Run tools/seed_orion_config.py to initialise."
        )
    updated_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE orion_config SET positive_prompt = ?, updated_at = ? "
            "WHERE mode = ? AND active = 1",
            (positive_prompt, updated_at, mode),
        )
