"""Validate Quantum's redacted database inventory for the shared backup contract."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REQUIRED_ROOT_FIELDS = {"schema_version", "project", "databases"}
REQUIRED_DATABASE_FIELDS = {
    "id",
    "path",
    "classification",
    "backup_allowed",
    "encryption",
    "key_env",
    "reason",
}
CLASSIFICATIONS = {
    "canonical",
    "coordination",
    "derived",
    "temporary",
    "legacy",
    "unknown",
    "approval-required",
}
DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
KEY_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
DENIED_CLASSIFICATIONS = {"derived", "temporary", "legacy", "unknown", "approval-required"}


def _validate_database_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise ValueError("each database inventory entry must be an object")
    missing = REQUIRED_DATABASE_FIELDS - entry.keys()
    unknown = entry.keys() - REQUIRED_DATABASE_FIELDS
    if missing:
        raise ValueError(f"database inventory entry missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown database inventory fields: {sorted(unknown)}")

    database_id = entry["id"]
    if not isinstance(database_id, str) or not IDENTIFIER_PATTERN.fullmatch(database_id):
        raise ValueError("database inventory id must be a safe identifier")

    path = entry["path"]
    if not isinstance(path, str) or not path.strip():
        raise ValueError("database inventory path must be non-empty")
    normalized_path = path.replace("\\", "/")
    path_parts = normalized_path.split("/")
    if (
        Path(normalized_path).is_absolute()
        or any(part in {"", ".", ".."} for part in path_parts)
        or "\\" in path
        or ":" in path
        or Path(normalized_path).suffix.lower() not in DATABASE_SUFFIXES
    ):
        raise ValueError("database inventory paths must be relative database paths")

    classification = entry["classification"]
    if classification not in CLASSIFICATIONS:
        raise ValueError("database inventory classification is invalid")
    if not isinstance(entry["backup_allowed"], bool):
        raise ValueError("database inventory backup_allowed must be boolean")
    if entry["backup_allowed"] and classification in DENIED_CLASSIFICATIONS:
        raise ValueError("generated, temporary, legacy, unknown, and approval-required databases are default-denied")
    if entry["encryption"] != "sqlcipher":
        raise ValueError("Quantum database inventory requires SQLCipher")

    key_env = entry["key_env"]
    if not isinstance(key_env, str) or not KEY_ENV_PATTERN.fullmatch(key_env):
        raise ValueError("database inventory key_env must be an environment variable name")
    if not isinstance(entry["reason"], str) or not entry["reason"].strip():
        raise ValueError("database inventory reason must be non-empty")


def load_database_inventory(path: Path) -> dict[str, Any]:
    """Load and validate Quantum database metadata without opening a database."""
    with Path(path).open(encoding="utf-8") as handle:
        inventory = json.load(handle)
    if not isinstance(inventory, dict):
        raise ValueError("database inventory root must be an object")
    missing = REQUIRED_ROOT_FIELDS - inventory.keys()
    unknown = inventory.keys() - REQUIRED_ROOT_FIELDS
    if missing:
        raise ValueError(f"database inventory missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown database inventory root fields: {sorted(unknown)}")
    if inventory["schema_version"] != 1:
        raise ValueError("unsupported database inventory schema version")
    if inventory["project"] != "quantum":
        raise ValueError("database inventory project must be quantum")

    databases = inventory["databases"]
    if not isinstance(databases, list) or not databases:
        raise ValueError("database inventory databases must be a non-empty list")

    ids: set[str] = set()
    paths: set[str] = set()
    for entry in databases:
        _validate_database_entry(entry)
        if entry["id"] in ids:
            raise ValueError(f"duplicate database inventory id: {entry['id']}")
        normalized_path = entry["path"].replace("\\", "/")
        if normalized_path in paths:
            raise ValueError(f"duplicate database inventory path: {normalized_path}")
        ids.add(entry["id"])
        paths.add(normalized_path)
    return inventory


def resolve_database_path(project_root: Path, entry: dict[str, Any]) -> Path:
    """Resolve an inventory locator under the project root without reading it."""
    _validate_database_entry(entry)
    root = Path(project_root).resolve()
    resolved = (root / entry["path"]).resolve()
    if root not in resolved.parents:
        raise ValueError("database inventory path escaped the project root")
    return resolved