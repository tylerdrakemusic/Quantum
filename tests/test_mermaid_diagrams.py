import json
from pathlib import Path
import re


DIAGRAMS_DIR = Path(__file__).parents[1] / "diagrams"
DIAGRAM_NAMES = (
    "quantum-architecture.mmd",
    "quantum-db-schema.mmd",
    "quantum-derived-cache-integrity.mmd",
    "quantum-package-compatibility.mmd",
    "quantum-randomness-service.mmd",
    "quantum-tech-stack.mmd",
)

EXPECTED_MANIFEST = {
    "diagrams/quantum-architecture.mmd": {
        "kind": "architecture",
        "category": "overview",
        "split_required": False,
        "lineage": {
            "parent": None,
            "derived_views": [
                "diagrams/quantum-derived-cache-integrity.mmd",
                "diagrams/quantum-randomness-service.mmd",
                "diagrams/quantum-package-compatibility.mmd",
            ],
        },
        "metrics": {"utf8_characters": 3015, "utf8_bytes": 3020, "nodes": 33, "edges": 20},
    },
    "diagrams/quantum-db-schema.mmd": {
        "kind": "database-schema",
        "category": "database-schema",
        "split_required": False,
        "lineage": {"parent": None, "derived_views": []},
        "metrics": {"utf8_characters": 3451, "utf8_bytes": 3451, "nodes": 10, "edges": 8},
    },
    "diagrams/quantum-derived-cache-integrity.mmd": {
        "kind": "derived-lifecycle",
        "category": "detail",
        "split_required": False,
        "lineage": {
            "parent": "diagrams/quantum-architecture.mmd",
            "derived_views": [],
        },
        "metrics": {"utf8_characters": 2743, "utf8_bytes": 2743, "nodes": 28, "edges": 14},
    },
    "diagrams/quantum-randomness-service.mmd": {
        "kind": "detail",
        "category": "detail",
        "split_required": False,
        "lineage": {
            "parent": "diagrams/quantum-architecture.mmd",
            "derived_views": [],
        },
        "metrics": {"utf8_characters": 3813, "utf8_bytes": 3822, "nodes": 47, "edges": 31},
    },
    "diagrams/quantum-package-compatibility.mmd": {
        "kind": "detail",
        "category": "detail",
        "split_required": False,
        "lineage": {
            "parent": "diagrams/quantum-architecture.mmd",
            "derived_views": [],
        },
        "metrics": {"utf8_characters": 1695, "utf8_bytes": 1695, "nodes": 11, "edges": 7},
    },
    "diagrams/quantum-tech-stack.mmd": {
        "kind": "technology-stack",
        "category": "technology-stack",
        "split_required": False,
        "lineage": {"parent": None, "derived_views": []},
        "metrics": {"utf8_characters": 3236, "utf8_bytes": 3247, "nodes": 30, "edges": 9},
    },
}

CATEGORY_BUDGETS = {
    "overview": {"max_utf8_bytes": 12000, "max_nodes": 40, "max_edges": 60},
    "detail": {"max_utf8_bytes": 12000, "max_nodes": 50, "max_edges": 80},
    "database-schema": {"max_utf8_bytes": 12000, "max_nodes": 40, "max_edges": 50},
    "technology-stack": {"max_utf8_bytes": 12000, "max_nodes": 30, "max_edges": 40},
    "workflow": {"max_utf8_bytes": 12000, "max_nodes": 35, "max_edges": 50},
}

EDGE_TOKENS = ("-->", "==>", "-.->", "---", "===", "}|")


def _measure_source(path: Path) -> dict[str, int | str]:
    source = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    normalized = source.replace("\n", "\r\n")
    lines = normalized.splitlines()
    return {
        "utf8_characters": len(normalized),
        "utf8_bytes": len(normalized.encode("utf-8")),
        "nodes": sum(1 for line in lines if _looks_like_node(line)),
        "edges": sum(1 for line in lines if any(token in line for token in EDGE_TOKENS)),
        "renderer_risk": "low",
        "fallback_risk": "medium" if ("%%{init:" in normalized or not normalized.isascii()) else "low",
    }


def _looks_like_node(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("%%", "subgraph", "classDef", "class ", "style ", "linkStyle")):
        return False
    return re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*(?:\[|\(|\{|<|-/|--)", stripped) is not None


def _split_required(category: str, metrics: dict[str, int | str]) -> bool:
    budget = CATEGORY_BUDGETS[category]
    return bool(
        metrics["nodes"] > budget["max_nodes"] or metrics["edges"] > budget["max_edges"]
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
    assert set(records) == set(EXPECTED_MANIFEST)

    for path, expected in EXPECTED_MANIFEST.items():
        record = records[path]
        assert record["kind"] == expected["kind"]
        assert record["lineage"] == expected["lineage"]
    assert all(
        {"kind", "renderer_risk", "fallback_risk", "split_required", "lineage"}
        <= record.keys()
        for record in records.values()
    )


def test_quantum_manifest_split_metadata_matches_measured_budget_contract() -> None:
    manifest = json.loads(
        (DIAGRAMS_DIR / "diagram-manifest.json").read_text(encoding="utf-8")
    )
    records = {record["path"]: record for record in manifest["diagrams"]}

    for path, expected in EXPECTED_MANIFEST.items():
        record = records[path]
        metrics = _measure_source(DIAGRAMS_DIR / Path(path).name)
        budget = CATEGORY_BUDGETS[expected["category"]]

        assert metrics["utf8_characters"] == expected["metrics"]["utf8_characters"]
        assert metrics["utf8_bytes"] == expected["metrics"]["utf8_bytes"]
        assert metrics["nodes"] == expected["metrics"]["nodes"]
        assert metrics["edges"] == expected["metrics"]["edges"]
        assert record["renderer_risk"] == "medium"
        assert record["fallback_risk"] == "medium"
        assert metrics["renderer_risk"] == "low"
        assert metrics["fallback_risk"] == "medium"
        assert metrics["utf8_bytes"] <= budget["max_utf8_bytes"]
        assert metrics["nodes"] <= budget["max_nodes"]
        assert metrics["edges"] <= budget["max_edges"]
        assert record["split_required"] is expected["split_required"]
        assert _split_required(expected["category"], metrics) is expected["split_required"]