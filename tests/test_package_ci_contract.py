from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_includes_legacy_shim_module() -> None:
    metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'py-modules = ["quantum_rt"]' in metadata


def test_ci_builds_checks_and_publishes_both_distribution_formats() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m build" in workflow
    assert "check_package_contents.py" in workflow
    assert "dist/*.whl" in workflow
    assert "dist/*.tar.gz" in workflow
    assert "distribution-artifacts" in workflow
    assert "package-content-report" in workflow
    assert "package-content-report.txt" in workflow


def test_ci_validates_the_exact_wheel_with_runtime_dependencies_outside_checkout() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m venv" in workflow
    assert "package_smoke.py" in workflow
    assert "--find-links dist dist/*.whl" in workflow
    assert "--no-cache-dir" in workflow
    assert "--no-index" not in workflow
    assert "package-install-validation" in workflow
    assert "install-validation.txt" in workflow
    assert "api-smoke.txt" in workflow
    assert "pytest-junit" in workflow


def test_package_validation_tools_enforce_offline_reports_and_exclusions() -> None:
    checker = (REPO_ROOT / "tools" / "check_package_contents.py").read_text(
        encoding="utf-8"
    )
    smoke = (REPO_ROOT / "tools" / "package_smoke.py").read_text(encoding="utf-8")

    assert "IBM_CLOUD_API_KEY" in checker
    assert "livecache" in checker
    assert "--report" in checker
    assert "qRandomBitstring(8)" in smoke
    assert "qsample" in smoke
    assert "qpermute" in smoke
    assert "--report" in smoke