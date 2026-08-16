from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.utils.database_backup_inventory import (
    load_database_inventory,
    resolve_database_path,
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
        "path": "src/data/quantumpsi.db",
        "classification": "canonical",
        "backup_allowed": True,
        "encryption": "sqlcipher",
        "key_env": "QUANTUM_DB_KEY",
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

    assert inventory["databases"][0]["key_env"] == "QUANTUM_DB_KEY"
    serialized = json.dumps(inventory).lower()
    assert "key_value" not in serialized
    assert "secret" not in serialized


def test_inventory_entries_are_configuration_driven(tmp_path: Path) -> None:
    future_database = _database(
        id="quantum-approved-future-store",
        path="src/data/future_store.sqlite3",
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


def test_resolve_database_path_stays_within_project_root(tmp_path: Path) -> None:
    assert resolve_database_path(tmp_path, _database()) == (
        tmp_path / "src" / "data" / "quantumpsi.db"
    )


@pytest.mark.parametrize(
    "entry",
    [
        _database(path="../../outside.db"),
        _database(
            id="quantum-orion-config",
            path="src/data/orion_config.db",
            classification="derived",
        ),
        _database(encryption="sqlite"),
        _database(key_env="not-an-environment-variable"),
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