"""
Rebuild quantumpsi.db with the new QUANTUM_DB_KEY.
Run AFTER setting QUANTUM_DB_KEY as a SYSTEM env var in an elevated terminal.

Usage:
    C:\\G\\python.exe f:\\⊕Workspace\\tmp\\rebuild_quantumpsi.py
"""
import os
import sys
from pathlib import Path

try:
    import sqlcipher3
except ImportError:
    print("ERROR: sqlcipher3 not installed. Run: C:\\G\\python.exe -m pip install sqlcipher3-wheels")
    sys.exit(1)

key = os.environ.get("QUANTUM_DB_KEY", "")
if not key:
    print("ERROR: QUANTUM_DB_KEY not set. Set it as SYSTEM env var first, then open a new terminal.")
    sys.exit(1)

DB_PATH = Path("f:\\") / "\u27e8\u03c8\u27e9Quantum" / "src" / "data" / "quantumpsi.db"
BACKUP_PATH = DB_PATH.with_suffix(".old_encrypted.db")

# Backup old (unrecoverable) encrypted DB
if DB_PATH.exists():
    DB_PATH.rename(BACKUP_PATH)
    print(f"Old encrypted DB moved to: {BACKUP_PATH}")

# Create new SQLCipher DB
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
conn = sqlcipher3.connect(str(DB_PATH))

key_hex = key.encode().hex()
conn.execute(f"PRAGMA key=\"x'{key_hex}'\"")  # nosec
conn.execute("PRAGMA cipher_page_size=4096")
conn.execute("PRAGMA kdf_iter=256000")
conn.execute("PRAGMA cipher_hmac_algorithm=HMAC_SHA512")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")

conn.execute("""
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
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_benchmarks_algorithm ON benchmarks(algorithm)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_benchmarks_backend ON benchmarks(backend)")
conn.commit()

# Verify
rows = conn.execute("SELECT count(*) FROM benchmarks").fetchone()[0]
conn.close()

print(f"quantumpsi.db rebuilt at: {DB_PATH}")
print(f"Benchmarks table: {rows} rows (fresh — data was not recoverable)")
print("Delete the .old_encrypted.db backup when satisfied:")
print(f"  del \"{BACKUP_PATH}\"")
