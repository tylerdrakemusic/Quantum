import json
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


def test_quantum_manifest_enumerates_sources_and_cache_integrity_lineage() -> None:
    manifest = json.loads(
        (DIAGRAMS_DIR / "diagram-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == 1
    assert manifest["repository"] == "quantum"
    records = {record["path"]: record for record in manifest["diagrams"]}
    assert set(records) == {f"diagrams/{name}" for name in DIAGRAM_NAMES}
    assert records["diagrams/quantum-architecture.mmd"]["lineage"] == {
        "parent": None,
        "derived_views": ["diagrams/quantum-derived-cache-integrity.mmd"],
    }
    assert records["diagrams/quantum-derived-cache-integrity.mmd"]["lineage"] == {
        "parent": "diagrams/quantum-architecture.mmd",
        "derived_views": [],
    }
    assert all(
        {"kind", "renderer_risk", "fallback_risk", "split_required", "lineage"}
        <= record.keys()
        for record in records.values()
    )