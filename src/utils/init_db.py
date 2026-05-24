"""Database connection utility for ⟨ψ⟩Quantum."""
import os
from pathlib import Path

from dotenv import load_dotenv
import sqlcipher3

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def _resolve_db_path() -> Path:
    override = os.environ.get("QUANTUM_DB_PATH")
    if override:
        return Path(override)

    default_path = Path(__file__).parent.parent / "data" / "quantumpsi.db"
    resolved_file = Path(__file__).resolve()
    if "worktrees" not in resolved_file.parts:
        return default_path

    canonical_path = Path(resolved_file.anchor) / "⟨ψ⟩Quantum" / "src" / "data" / "quantumpsi.db"
    if canonical_path.exists():
        return canonical_path
    return default_path


DB_PATH = _resolve_db_path()


def get_connection() -> sqlcipher3.Connection:
    """Return a sqlcipher3 connection to the ⟨ψ⟩Quantum database."""
    key = os.environ.get("QUANTUM_DB_KEY", "")
    if not key:
        raise RuntimeError("QUANTUM_DB_KEY not set")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlcipher3.connect(str(DB_PATH))
    key_hex = key.encode().hex()
    conn.execute(f"PRAGMA key=\"x'{key_hex}'\"")  # nosec B608 — SQLCipher key init, key from env var not user input
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

    -- VQE molecular simulation runs (FR-20260430-vqe-aer-bench)
    CREATE TABLE IF NOT EXISTS vqe_runs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date        TEXT    NOT NULL,
        molecule        TEXT    NOT NULL,
        bond_length_ang REAL,
        n_qubits        INTEGER NOT NULL,
        n_pauli_terms   INTEGER NOT NULL,
        ansatz          TEXT    NOT NULL,
        n_parameters    INTEGER NOT NULL,
        optimizer       TEXT    NOT NULL,
        final_energy    REAL    NOT NULL,
        fci_reference   REAL    NOT NULL,
        delta_ha        REAL    NOT NULL,
        n_evals         INTEGER NOT NULL,
        wall_clock_sec  REAL    NOT NULL,
        backend         TEXT    NOT NULL,
        timestamp       TEXT    NOT NULL,
        created_at      TEXT    DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_vqe_runs_run_date ON vqe_runs(run_date);
    CREATE INDEX IF NOT EXISTS idx_vqe_runs_molecule ON vqe_runs(molecule);

    CREATE TABLE IF NOT EXISTS policy_events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        event_time   TEXT    NOT NULL,
        policy_id    TEXT    NOT NULL,
        event_type   TEXT    NOT NULL,
        status       TEXT    NOT NULL,
        source       TEXT    NOT NULL,
        detail       TEXT,
        next_run_at  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_policy_events_policy_time
        ON policy_events(policy_id, event_time);

    -- Cache depletion guard health log (FR-20260524-quantum-cache-depletion-guard)
    CREATE TABLE IF NOT EXISTS cache_health_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              TEXT    NOT NULL,
        bits_remaining  INTEGER NOT NULL,
        capacity_bits   INTEGER NOT NULL,
        pct_full        REAL    NOT NULL,
        action_taken    TEXT    NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_cache_health_log_ts ON cache_health_log(ts);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
