from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.utils.database_backup_inventory import (
    build_backup_manifest,
    load_database_inventory,
    resolve_database_path,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "⊕Workspace" / ".worktrees" / "feature-FR-20260816-workspace-local-database-backup"))
import src.utils  # noqa: E402
src.utils.__path__.insert(0, str(Path(__file__).resolve().parents[4] / "⊕Workspace" / ".worktrees" / "feature-FR-20260816-workspace-local-database-backup" / "src" / "utils"))
from src.utils.database_backup import (  # noqa: E402
    DatabaseBackup,
    LocalVolumeDestination,
    discover_and_validate_manifest,
    validate_recent_backups,
)


def _inventory(databases: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": "quantum",
        "databases": databases,
    }


def _database(**overrides: object) -> dict[str, object]:
    database: dict[str, object] = {
        "id": "quantum-quantumpsi",
        "locator": "quantum/application-store",
        "basename": "quantumpsi.db",
        "classification": "canonical",
        "backup_allowed": True,
        "encryption": "sqlcipher",
        "key_env_var": "QUANTUM_DB_KEY",
        "reason": "Authoritative encrypted Quantum application database.",
    }
    database.update(overrides)
    return database


def test_committed_inventory_registers_canonical_encrypted_store() -> None:
    project_root = Path(__file__).resolve().parent.parent
    inventory = load_database_inventory(
        project_root / "src" / "config" / "database_backup_inventory.json"
    )

    assert inventory["databases"] == [_database()]


def test_inventory_contains_key_reference_but_never_key_material(
    tmp_path: Path,
) -> None:
    inventory_path = tmp_path / "database_backup_inventory.json"
    inventory_path.write_text(
        json.dumps(_inventory([_database()])), encoding="utf-8"
    )

    inventory = load_database_inventory(inventory_path)

    assert inventory["databases"][0]["key_env_var"] == "QUANTUM_DB_KEY"
    serialized = json.dumps(inventory).lower()
    assert "key_value" not in serialized
    assert "secret" not in serialized


def test_inventory_entries_are_configuration_driven(tmp_path: Path) -> None:
    future_database = _database(
        id="quantum-approved-future-store",
        locator="quantum/future-store",
        basename="future_store.sqlite3",
        reason="Approved future canonical encrypted store.",
    )
    inventory_path = tmp_path / "database_backup_inventory.json"
    inventory_path.write_text(
        json.dumps(_inventory([_database(), future_database])), encoding="utf-8"
    )

    inventory = load_database_inventory(inventory_path)

    assert [entry["id"] for entry in inventory["databases"]] == [
        "quantum-quantumpsi",
        "quantum-approved-future-store",
    ]


def test_inventory_projects_new_entry_into_generic_backup_manifest(tmp_path: Path) -> None:
    inventory_path = tmp_path / "database_backup_inventory.json"
    inventory_path.write_text(json.dumps(_inventory([_database(
        id="quantum-approved-future-store",
        locator="quantum/future-store",
        basename="future_store.sqlite3",
    )])), encoding="utf-8")

    manifest = build_backup_manifest(load_database_inventory(inventory_path))

    assert manifest["databases"][0]["path"] == "quantum/future-store"
    assert manifest["databases"][0]["discovery"] == {
        "project": "quantum",
        "basename": "future_store.sqlite3",
    }
    assert manifest["databases"][0]["key_env"] == "QUANTUM_DB_KEY"


def test_resolve_database_path_stays_within_project_root(tmp_path: Path) -> None:
    assert resolve_database_path(tmp_path, _database()) == (
        tmp_path / "src" / "data" / "quantumpsi.db"
    )


@pytest.mark.parametrize(
    "entry",
    [
        _database(locator="../outside-store"),
        _database(
            id="quantum-orion-config",
            path="src/data/orion_config.db",
            classification="derived",
        ),
        _database(encryption="sqlite"),
        _database(key_env_var="not-an-environment-variable"),
            _database(key_env_var="not-an-environment-variable"),
        _database(backup_allowed=True, classification="approval-required"),
    ],
)
def test_inventory_rejects_unsafe_or_excluded_database_entries(
    tmp_path: Path, entry: dict[str, object]
) -> None:
    inventory_path = tmp_path / "database_backup_inventory.json"
    inventory_path.write_text(
        json.dumps(_inventory([entry])), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        load_database_inventory(inventory_path)


def test_committed_inventory_runs_shared_backup_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKSPACE_BACKUP_MANIFEST_KEY", "test-quantum-key")
    project_root = Path(__file__).resolve().parent.parent
    manifest = build_backup_manifest(load_database_inventory(project_root / "src" / "config" / "database_backup_inventory.json"))
    source_root = tmp_path / "quantum"
    source = source_root / "src" / "data" / "quantumpsi.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"isolated-fixture")
    destination = LocalVolumeDestination(tmp_path / "external", "quantum-volume", provision=True)
    for second in (0, 1):
        DatabaseBackup(manifest, {"quantum": source_root}, destination, "quantum-volume", now=lambda second=second: f"2026-08-16T12:00:0{second}Z", retention=1).run()
    assert len(list((destination.path() / "generations").iterdir())) == 1
    drift = source_root / "src" / "data" / "unexpected.db"
    drift.write_bytes(b"drift")
    with pytest.raises(ValueError, match="unregistered"):
        discover_and_validate_manifest(manifest, {"quantum": source_root})
    drift.unlink()
    manifest_path = next((destination.path() / "generations").glob("*/manifest.json"))
    restore_root = tmp_path / "restore"
    DatabaseBackup.restore(manifest_path, destination, restore_root, True, "quantum-volume", allow_canonical_restore=True)
    assert (restore_root / "quantum/application-store").read_bytes() == b"isolated-fixture"
    validate_recent_backups(destination, "quantum-volume", restore_validator=lambda *_: None)
    assert str(restore_root) not in (destination.path() / "backup-audit.jsonl").read_text(encoding="utf-8")