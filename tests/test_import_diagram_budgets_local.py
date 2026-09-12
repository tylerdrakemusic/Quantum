"""RED test: confirm we can import diagram_budgets contract from local Quantum utils."""

import pytest


def test_diagram_budgets_imports_from_local_quantum_utils() -> None:
    """Verify diagram_budgets is available locally without Workspace path hardcoding."""
    # This test documents the failure case: import from Quantum's own utils
    # without hardcoding F:\⊕Workspace path.
    from src.utils.diagram_budgets import (
        DiagramCategory,
        DiagramSpec,
        Traceability,
        measure_source,
        validate_diagram,
    )

    # Confirm the contract types exist and are usable
    assert issubclass(DiagramCategory, str)
    assert hasattr(DiagramCategory, "OVERVIEW")
    assert callable(measure_source)
    assert callable(validate_diagram)
    assert DiagramSpec is not None
    assert Traceability is not None
