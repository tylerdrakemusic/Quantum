import json
from pathlib import Path

import sys


sys.path.insert(0, r"F:\⊕Workspace")

from src.utils.diagram_budgets import DiagramCategory, DiagramSpec, Traceability, measure_source, validate_diagram


DIAGRAMS_DIR = Path(__file__).parents[1] / "diagrams"
DIAGRAM_NAMES = (
    "quantum-architecture.mmd",
    "quantum-db-schema.mmd",
    "quantum-derived-cache-integrity.mmd",
    "quantum-package-compatibility.mmd",
    "quantum-randomness-service.mmd",
    "quantum-tech-stack.mmd",
)


def test_quantum_mermaid_sources_preserve_traceability() -> None:
    diagrams = {
        name: (DIAGRAMS_DIR / name).read_text(encoding="utf-8")
        for name in DIAGRAM_NAMES
    }

    assert all(source.strip() for source in diagrams.values())
    assert all(source.count("\n") + 1 <= 120 for source in diagrams.values())
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
        "derived_views": [
            "diagrams/quantum-derived-cache-integrity.mmd",
            "diagrams/quantum-randomness-service.mmd",
            "diagrams/quantum-package-compatibility.mmd",
        ],
    }
    assert records["diagrams/quantum-derived-cache-integrity.mmd"]["lineage"] == {
        "parent": "diagrams/quantum-architecture.mmd",
        "derived_views": [],
    }
    assert records["diagrams/quantum-package-compatibility.mmd"]["lineage"] == {
        "parent": "diagrams/quantum-architecture.mmd",
        "derived_views": [],
    }
    assert records["diagrams/quantum-randomness-service.mmd"]["lineage"] == {
        "parent": "diagrams/quantum-architecture.mmd",
        "derived_views": [],
    }
    assert all(
        {"kind", "renderer_risk", "fallback_risk", "split_required", "lineage"}
        <= record.keys()
        for record in records.values()
    )


def test_quantum_manifest_split_metadata_matches_measured_budget_contract() -> None:
    manifest = json.loads((DIAGRAMS_DIR / "diagram-manifest.json").read_text(encoding="utf-8"))
    kind_to_category = {
        "architecture": DiagramCategory.OVERVIEW,
        "database-schema": DiagramCategory.DATABASE_SCHEMA,
        "derived-lifecycle": DiagramCategory.DETAIL,
        "detail": DiagramCategory.DETAIL,
        "technology-stack": DiagramCategory.TECHNOLOGY_STACK,
        "workflow": DiagramCategory.WORKFLOW,
    }
    records = {record["path"]: record for record in manifest["diagrams"]}

    for path, record in records.items():
        metrics = measure_source(DIAGRAMS_DIR / Path(path).name)
        result = validate_diagram(
            DiagramSpec(
                path=path,
                category=kind_to_category[record["kind"]],
                metrics=metrics,
                traceability=Traceability(
                    parent=record["lineage"]["parent"],
                    derived_views=tuple(record["lineage"]["derived_views"]),
                ),
                is_derived_view=record["lineage"]["parent"] is not None,
            )
        )

        assert record["split_required"] is result.split_required, (path, result.findings)
        assert result.is_compliant or result.split_required, (path, result.findings)