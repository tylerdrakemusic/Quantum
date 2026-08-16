# Quantum Database Backup Inventory

This project contributes a redacted inventory to the shared, manifest-driven
database backup contract. The inventory records database paths and policy
metadata only. It never opens, copies, uploads, or prints database contents or
encryption keys.

The approved entry is the canonical SQLCipher database at
`src/data/quantumpsi.db`, unlocked at runtime only through the
`QUANTUM_DB_KEY` environment variable used by `src/utils/init_db.py`.

Future approved Quantum databases must be added as inventory entries with a
safe relative path, `sqlcipher` encryption, and an environment-variable key
reference. Generated configuration stores, temporary files, legacy stores,
unknown stores, and approval-required stores remain denied and are not added to
the approved inventory.

Validate the inventory from this worktree with:

```powershell
$env:PYTHONUTF8 = "1"
& "C:\G\python.exe" -m pytest tests/test_database_backup_inventory.py -q
```