"""Machine-checkable budgets for Mermaid diagram sources (Quantum local contract).

This is a minimal local implementation for Quantum's diagram validation tests.
It replicates only the contract types and measurement/validation functions needed
by test_mermaid_diagrams.py, without external dependencies on Workspace utilities
or federation discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


class DiagramCategory(str, Enum):
    """Diagram classification for budget assignment."""

    OVERVIEW = "overview"
    DETAIL = "detail"
    DATABASE_SCHEMA = "database-schema"
    TECHNOLOGY_STACK = "technology-stack"
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class DiagramMetrics:
    """Measured properties of a Mermaid diagram source."""

    utf8_characters: int
    utf8_bytes: int
    nodes: int
    edges: int
    renderer_url_risk: str
    fallback_risk: str


@dataclass(frozen=True)
class Traceability:
    """Parent/derived-view lineage for a diagram."""

    parent: str | None
    derived_views: tuple[str, ...]


@dataclass(frozen=True)
class DiagramSpec:
    """Complete specification of a diagram including metrics and lineage."""

    path: str
    category: DiagramCategory
    metrics: DiagramMetrics
    traceability: Traceability
    is_derived_view: bool = False


@dataclass(frozen=True)
class DiagramBudget:
    """Limits for a diagram category."""

    max_utf8_characters: int
    max_utf8_bytes: int
    max_nodes: int
    max_edges: int
    max_renderer_url_risk: str = "medium"
    max_fallback_risk: str = "medium"
    split_at_nodes: int | None = None
    split_at_edges: int | None = None


@dataclass(frozen=True)
class Finding:
    """A validation issue or constraint."""

    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating one diagram against its budget."""

    findings: tuple[Finding, ...]
    split_required: bool

    @property
    def is_compliant(self) -> bool:
        return not self.findings


RISK_LEVELS = {"low": 0, "medium": 1, "high": 2}

# Quantum-local diagram budgets (derived from Workspace budgets).
# These are deterministic local values; no cross-repo discovery needed.
BUDGETS: dict[DiagramCategory, DiagramBudget] = {
    DiagramCategory.OVERVIEW: DiagramBudget(
        8000, 12000, 40, 60, split_at_nodes=40, split_at_edges=60
    ),
    DiagramCategory.DETAIL: DiagramBudget(
        8000, 12000, 50, 80, split_at_nodes=50, split_at_edges=80
    ),
    DiagramCategory.DATABASE_SCHEMA: DiagramBudget(
        8000, 12000, 40, 50, split_at_nodes=40, split_at_edges=50
    ),
    DiagramCategory.TECHNOLOGY_STACK: DiagramBudget(
        8000, 12000, 30, 40, split_at_nodes=30, split_at_edges=40
    ),
    DiagramCategory.WORKFLOW: DiagramBudget(
        8000, 12000, 35, 50, split_at_nodes=35, split_at_edges=50
    ),
}


def validate_diagram(spec: DiagramSpec) -> ValidationResult:
    """Validate one diagram against its category budget and lineage rules."""
    budget = BUDGETS[spec.category]
    metrics = spec.metrics
    findings: list[Finding] = []

    # Check node and edge limits.
    limits = (
        ("nodes", metrics.nodes, budget.max_nodes),
        ("edges", metrics.edges, budget.max_edges),
    )
    for code, value, limit in limits:
        if value > limit:
            findings.append(Finding(code, f"{code}={value} exceeds budget {limit}"))

    # Check risk levels.
    for code, value, limit in (
        ("renderer_url_risk", metrics.renderer_url_risk, budget.max_renderer_url_risk),
        ("fallback_risk", metrics.fallback_risk, budget.max_fallback_risk),
    ):
        if value not in RISK_LEVELS or RISK_LEVELS[value] > RISK_LEVELS[limit]:
            findings.append(
                Finding(code, f"{code}={value!r} exceeds allowed risk {limit!r}")
            )

    # Check split requirements.
    split_required = (
        (
            budget.split_at_nodes is not None
            and metrics.nodes > budget.split_at_nodes
        )
        or (
            budget.split_at_edges is not None
            and metrics.edges > budget.split_at_edges
        )
    )
    if split_required:
        findings.append(
            Finding("split_required", f"{spec.path} exceeds its category split threshold")
        )

    # Check traceability constraints.
    if spec.is_derived_view and not spec.traceability.parent:
        findings.append(
            Finding("traceability", "derived views must name their parent diagram")
        )
    if not spec.is_derived_view and any(
        not view for view in spec.traceability.derived_views
    ):
        findings.append(
            Finding(
                "traceability", "parent diagrams must declare non-empty derived view paths"
            )
        )

    return ValidationResult(tuple(findings), split_required)


def measure_source(path: Path) -> DiagramMetrics:
    """Measure a Mermaid source using the inventory measurement contract."""
    with path.open("r", encoding="utf-8", newline="") as source_file:
        source = source_file.read()

    # Normalize line endings for consistent measurement.
    source = source.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    lines = source.splitlines()

    # Count nodes and edges using heuristics.
    node_count = sum(1 for line in lines if _looks_like_node(line))
    edge_count = sum(
        1
        for line in lines
        if any(operator in line for operator in ("-->", "==>", "-.->", "---", "===", "}|"))
    )

    return DiagramMetrics(
        utf8_characters=len(source),
        utf8_bytes=len(source.encode("utf-8")),
        nodes=node_count,
        edges=edge_count,
        renderer_url_risk="low",
        fallback_risk="medium"
        if ("%%{init:" in source or not source.isascii())
        else "low",
    )


def _looks_like_node(line: str) -> bool:
    """Heuristic to identify Mermaid node definitions."""
    stripped = line.strip()
    if not stripped or stripped.startswith(
        ("%%", "subgraph", "classDef", "class ", "style ", "linkStyle")
    ):
        return False
    return re.match(
        r"^[A-Za-z_][A-Za-z0-9_-]*\s*(?:\[|\(|\{|<|-/|--)", stripped
    ) is not None
