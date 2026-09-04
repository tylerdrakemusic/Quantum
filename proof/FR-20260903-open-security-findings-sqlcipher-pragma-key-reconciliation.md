# Accepted SQLCipher PRAGMA Key Finding Reconciliation

**FR:** `FR-20260903-open-security-findings-all-repositories`
**Child:** `519`
**Repository:** `⟨ψ⟩Quantum`
**Finding:** `28e1489f8d2c002d`
**Central disposition:** `accepted`
**Reconciliation date:** 2026-09-04

## Disposition authority

The canonical `workspace.vulnerabilities` record for finding
`28e1489f8d2c002d` is retained as `accepted`. This artifact records the
technical reconciliation only; it does not modify the vulnerability record,
its override note, or any other central disposition data.

The sibling Quantum validation artifact records that the Quantum open-only
query returned zero rows and that this finding is one of three historical
Quantum-path records, all already non-open:

- [Quantum child validation](FR-20260903-open-security-findings-quantum-child-validation.md)
- [Finding reconciliation](FR-20260903-open-security-findings-quantum-finding-reconciliation.md)

## Exact code path

The scanner finding maps to
[`src/utils/init_db.py`](../src/utils/init_db.py):

1. `get_connection()` reads `QUANTUM_DB_KEY` from the process environment.
2. An empty or unset value raises `RuntimeError("QUANTUM_DB_KEY not set")` before
   a database connection is opened.
3. The supplied Python string is encoded with `key.encode()`, using Python's
   default UTF-8 encoding, and converted to lowercase hexadecimal with
   `.hex()`.
4. Only that hexadecimal value is interpolated into the SQLCipher key setup
   statement:

   ```python
   conn.execute(f"PRAGMA key=\"x'{key_hex}'\"")
   ```

5. The connection then executes fixed, source-controlled PRAGMA statements
   for page size, KDF iteration count, HMAC algorithm, WAL mode, foreign keys,
   and busy timeout.

The database initialization path is `init_db()` -> `get_connection()` -> the
SQLCipher `PRAGMA key` statement. The separate `tools/rebuild_db.py` utility
uses the same environment-key-to-hex construction for an administrative
rebuild path; it is not a request-handler input path.

## Input constraints and encoding

The input is constrained to the `QUANTUM_DB_KEY` process environment variable.
It is not taken from a URL, form field, request body, command-line argument,
database row, or other caller-controlled SQL fragment. The only validation at
this boundary is presence: unset and empty values are rejected.

Before interpolation, UTF-8 bytes are rendered as hexadecimal characters.
Therefore `key_hex` can contain only `[0-9a-f]` and has an even length. Quotes,
semicolons, comment markers, whitespace, and SQL keywords in the original key
cannot survive as SQL syntax. The surrounding pragma grammar is fixed in
source, and the value is used as SQLCipher's hex-literal key payload.

## Why this is not exploitable SQL injection

The static scanner correctly identifies an f-string passed to `execute()`, but
the interpolated value is a deterministic encoding of a secret environment
value, not raw attacker-controlled SQL. An attacker would need control of the
process environment itself, which is a deployment or secret-management breach
outside this database API's input boundary. Even arbitrary bytes in the key
are transformed into the restricted hexadecimal alphabet before interpolation.

The statement is required by SQLCipher because the key pragma must be issued
on the newly opened connection before normal database operations. Replacing it
with ordinary parameter binding would not establish the SQLCipher key in the
same way. The existing `# nosec B608` annotation documents this narrowly
scoped exception.

## Test evidence

Focused executable evidence for the owning database path is:

```text
C:\G\python.exe -m pytest tests/test_init_db.py tests/test_monthly_scheduler_db_race.py -q
4 passed in 0.41s
```

The existing child validation also recorded these passing focused checks:

```text
C:\G\python.exe -m pytest tests/test_cache_integrity.py tests/test_init_db.py tests/test_policy_auditor.py -q
18 passed in 0.82s

C:\G\python.exe -m pytest tests/test_cache_depletion_guard.py tests/test_database_backup_inventory.py tests/test_job_retry_supervisor.py tests/test_monthly_scheduler_db_race.py -q
29 passed in 36.42s
```

The broader non-playwright/non-live suite was interrupted during later
SQLCipher schema setup and is not represented as a passing result. The
scanner's separate JSON ledger reported `58 findings, 0 open`; it corroborates
the zero-open result but is not the disposition authority.

## Conclusion

Finding `28e1489f8d2c002d` remains correctly `accepted` as a documented
SQLCipher initialization exception. No remediation or central-record mutation
is required for this finding.