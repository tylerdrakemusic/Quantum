from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src" / "utils") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "utils"))

import init_db


def test_init_db_closes_schema_connection_when_initialization_fails(monkeypatch) -> None:
    connection = Mock()
    connection.cursor.return_value = Mock()
    connection.commit.side_effect = RuntimeError("schema commit failed")
    monkeypatch.setattr(init_db, "get_connection", lambda: connection)

    with pytest.raises(RuntimeError, match="schema commit failed"):
        init_db.init_db()

    connection.close.assert_called_once_with()