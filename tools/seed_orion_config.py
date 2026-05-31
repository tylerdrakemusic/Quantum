"""Seed orion_config.db with initial active Orion portrait prompts.

Creates one active row per mode (idle, active, result_ready). Idempotent —
skips insertion if an active row already exists for a given mode.

Usage::

    C:\\G\\python.exe tools/seed_orion_config.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve DB path relative to project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = _PROJECT_ROOT / "src" / "data" / "orion_config.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS orion_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT    NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    positive_prompt TEXT    NOT NULL,
    negative_prompt TEXT,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orion_config_mode ON orion_config(mode, active);
"""

# ---------------------------------------------------------------------------
# Default prompts per mode
# ---------------------------------------------------------------------------
_PROMPTS: dict[str, dict[str, str]] = {
    "idle": {
        "positive": (
            "A photorealistic half-body portrait of a brilliant, focused quantum physicist "
            "woman in her early 30s, waist up. Dark physics laboratory setting with holographic "
            "quantum circuit diagrams floating in the background. "
            "Deep indigo and purple rim lighting creating an ethereal glow around her. "
            "Wearing a dark fitted turtleneck, calm studious expression, studying holographic equations. "
            "Soft ambient indigo glow fills the dark lab. Confident, intelligent demeanour. "
            "Canon EOS 5D Mark IV, f/1.8, shallow depth of field, ultra-realistic RAW photo."
        ),
        "negative": (
            "illustration, painting, drawing, sketch, anime, manga, 3D render, CGI, "
            "ugly, deformed, poorly drawn hands, extra limbs, blurry, text, watermark"
        ),
    },
    "active": {
        "positive": (
            "A photorealistic half-body portrait of a sharp, determined quantum physicist "
            "woman in her early 30s, waist up. Futuristic quantum computing workstation setting. "
            "Green circuit monitor displays glowing in the background, active computation visualisations. "
            "Deep indigo rim lighting, dark fitted turtleneck. "
            "Focused intense expression at work, hands near holographic controls. "
            "Professional, driven, highly capable. "
            "Canon EOS 5D Mark IV, f/1.8, shallow depth of field, ultra-realistic RAW photo."
        ),
        "negative": (
            "illustration, painting, drawing, sketch, anime, manga, 3D render, CGI, "
            "ugly, deformed, poorly drawn hands, extra limbs, blurry, text, watermark"
        ),
    },
    "result_ready": {
        "positive": (
            "A photorealistic half-body portrait of a triumphant, satisfied quantum physicist "
            "woman in her early 30s, waist up. Bright holographic circuit displays showing "
            "successful quantum computation results in the background. "
            "Brilliant indigo and violet rim lighting illuminating a slight satisfied smile. "
            "Dark fitted turtleneck, confident composed expression of achievement. "
            "Bright successful results visible on quantum circuit monitors. "
            "Canon EOS 5D Mark IV, f/1.8, shallow depth of field, ultra-realistic RAW photo."
        ),
        "negative": (
            "illustration, painting, drawing, sketch, anime, manga, 3D render, CGI, "
            "ugly, deformed, poorly drawn hands, extra limbs, blurry, text, watermark"
        ),
    },
}


def seed() -> None:
    """Create and seed orion_config.db (idempotent)."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.executescript(_CREATE_TABLE_SQL)
        conn.commit()

        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for mode, prompts in _PROMPTS.items():
            # Check if an active row already exists for this mode
            row = conn.execute(
                "SELECT id FROM orion_config WHERE mode = ? AND active = 1 LIMIT 1",
                (mode,),
            ).fetchone()
            if row is not None:
                print(f"[seed] Active row already exists for mode={mode!r} (id={row[0]}). Skipping.")
                continue
            conn.execute(
                "INSERT INTO orion_config (mode, active, positive_prompt, negative_prompt, updated_at) "
                "VALUES (?, 1, ?, ?, ?)",
                (mode, prompts["positive"], prompts.get("negative"), now),
            )
            inserted += 1

        conn.commit()
        if inserted:
            print(f"[seed] Inserted {inserted} prompt row(s) into {_DB_PATH}")
        else:
            print(f"[seed] All modes already seeded in {_DB_PATH}. Nothing to do.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
    sys.exit(0)
