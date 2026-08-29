from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_default_pytest_configuration_does_not_deselect_slow_tests() -> None:
    pytest_config = (PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert 'addopts = -v --tb=short -m "not slow"' not in pytest_config


def test_ci_reports_conditional_skip_reasons() -> None:
    pytest_config = (PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "-rs" in pytest_config


def test_canonical_ci_command_reports_skip_reasons() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )

    assert 'run: pytest -v --tb=short -rs -m "not ci_long_running" --junitxml=tmp/pytest-junit.xml' in workflow


def test_canonical_ci_bounds_exactly_the_lih_test_with_reason_and_count() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )
    vqe_tests = (PROJECT_ROOT / "tests" / "test_vqe.py").read_text(encoding="utf-8")

    assert "ci_long_running" in vqe_tests
    assert "tests/test_vqe.py::test_lih_chemical_accuracy" in workflow
    assert "expected_count=1" in workflow
    assert "--collect-only -qq -m ci_long_running" in workflow
    assert "CI bounded exclusion count:" in workflow
    assert "LiH" in workflow
    assert "15 min" in workflow
    assert 'run: pytest -v --tb=short -rs -m "not ci_long_running" --junitxml=tmp/pytest-junit.xml' in workflow
    assert "continue-on-error" not in workflow


def test_qiskit_eve_qber_uses_stable_small_sample_average() -> None:
    qkd_tests = (PROJECT_ROOT / "tests" / "test_qkd_bb84.py").read_text(
        encoding="utf-8"
    )
    qiskit_test = qkd_tests.split(
        "    def test_qiskit_eve_qber_above_threshold", 1
    )[1].split("\n\n", 1)[0]

    assert "for _ in range(10):" in qiskit_test
    assert "assert avg_qber >= 0.15" in qiskit_test


def test_workspace_dependent_tests_are_explicitly_classified() -> None:
    pytest_config = (PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")
    portal_tests = (PROJECT_ROOT / "tests" / "test_bfx_orion_portal_server.py").read_text(
        encoding="utf-8"
    )

    assert "ci_unavailable:" in pytest_config
    assert "pytest.mark.ci_unavailable" in portal_tests
