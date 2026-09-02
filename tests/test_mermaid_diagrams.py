from pathlib import Path


DIAGRAMS_DIR = Path(__file__).parents[1] / "diagrams"
DIAGRAM_NAMES = (
    "quantum-architecture.mmd",
    "quantum-db-schema.mmd",
    "quantum-derived-cache-integrity.mmd",
    "quantum-tech-stack.mmd",
)
RENDERING_BUDGET_LINES = 120


def test_quantum_mermaid_sources_fit_local_rendering_budget_and_traceability() -> None:
    diagrams = {
        name: (DIAGRAMS_DIR / name).read_text(encoding="utf-8")
        for name in DIAGRAM_NAMES
    }

    assert all(
        len(source.splitlines()) <= RENDERING_BUDGET_LINES
        for source in diagrams.values()
    )
    assert "%% is_derived_view=false" in diagrams["quantum-architecture.mmd"]
    assert (
        "%% Traceability.derived_views: diagrams/quantum-derived-cache-integrity.mmd"
        in diagrams["quantum-architecture.mmd"]
    )
    assert "%% is_derived_view=true" in diagrams["quantum-derived-cache-integrity.mmd"]
    assert (
        "%% Traceability.parent: diagrams/quantum-architecture.mmd"
        in diagrams["quantum-derived-cache-integrity.mmd"]
    )