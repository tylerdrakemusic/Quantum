import sys
sys.path.insert(0, '.')

# Import and verify the local diagram_budgets work
from src.utils.diagram_budgets import DiagramCategory, DiagramSpec, Traceability, measure_source, validate_diagram
print(f"✓ Imported from local src.utils.diagram_budgets")

# Verify test file can import
from tests import test_mermaid_diagrams
print(f"✓ Imported test_mermaid_diagrams")

# Verify the DIAGRAMS_DIR and test data exist
from pathlib import Path
diagrams_dir = Path("diagrams")
assert diagrams_dir.is_dir(), f"diagrams dir not found: {diagrams_dir}"
print(f"✓ Diagrams directory found: {diagrams_dir}")

# Verify manifest exists
manifest_path = diagrams_dir / "diagram-manifest.json"
assert manifest_path.is_file(), f"manifest not found: {manifest_path}"
print(f"✓ Manifest file found: {manifest_path}")

# Quick sanity check on measurement
test_file = diagrams_dir / "quantum-architecture.mmd"
if test_file.exists():
    metrics = measure_source(test_file)
    print(f"✓ measure_source works: {metrics.nodes} nodes, {metrics.edges} edges")
else:
    print(f"  (skipped measure_source check - test file not found)")

print("\nAll import and contract checks passed!")
