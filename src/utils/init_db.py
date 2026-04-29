"""Database connection utility for ⟨ψ⟩Quantum."""
import os
from pathlib import Path

from dotenv import load_dotenv
import sqlcipher3

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

DB_PATH = Path(__file__).parent.parent / "data" / "quantumpsi.db"


def get_connection() -> sqlcipher3.Connection:
    """Return a sqlcipher3 connection to the ⟨ψ⟩Quantum database."""
    key = os.environ.get("QUANTUM_DB_KEY", "")
    if not key:
        raise RuntimeError("QUANTUM_DB_KEY not set")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher3.connect(str(DB_PATH))
    key_hex = key.encode().hex()
    conn.execute(f"PRAGMA key=\"x'{key_hex}'\"")
    conn.execute("PRAGMA cipher_page_size=4096")
    conn.execute("PRAGMA kdf_iter=256000")
    conn.execute("PRAGMA cipher_hmac_algorithm=HMAC_SHA512")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlcipher3.Row
    return conn


def init_db() -> None:
    """Create all tables if they do not exist."""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS benchmarks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        algorithm       TEXT NOT NULL,
        total_time_sec  REAL NOT NULL,
        required_qubits INTEGER NOT NULL,
        n_value         INTEGER NOT NULL,
        order_r         INTEGER,
        factor1         INTEGER,
        factor2         INTEGER,
        backend         TEXT NOT NULL,
        timestamp       TEXT NOT NULL,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_benchmarks_algorithm ON benchmarks(algorithm);
    CREATE INDEX IF NOT EXISTS idx_benchmarks_backend ON benchmarks(backend);

    -- QPU-specific Shor's runs (FR-20260428-shors-monthly-qpu-bench)
    CREATE TABLE IF NOT EXISTS shors_qpu_bench (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date     TEXT    NOT NULL,
        n_value      INTEGER NOT NULL,
        n_qubits     INTEGER NOT NULL,
        success      INTEGER NOT NULL,
        factor_found TEXT,
        qpu_seconds  REAL    NOT NULL,
        backend      TEXT    NOT NULL,
        notes        TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_sqb_run_date ON shors_qpu_bench(run_date);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
