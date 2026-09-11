from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "deploy-randomness-service.yml"


def test_production_deployment_workflow_is_success_gated_and_environment_protected():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" in workflow
    assert 'workflows: ["test"]' in workflow
    assert "types: [completed]" in workflow
    assert "branches: [main]" in workflow
    assert "workflow_run.conclusion == 'success'" in workflow
    assert "workflow_run.head_branch == 'main'" in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment:" in workflow
    assert "name: production" in workflow


def test_deployment_workflow_uses_ci_root_and_existing_safe_entrypoint():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    deploy_script = (WORKFLOW.parents[2] / "tools" / "deploy_randomness_service.ps1").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@v4" in workflow
    assert "working-directory: ${{ github.workspace }}" in workflow
    assert "Set-Location $env:GITHUB_WORKSPACE" in workflow
    assert "tools/deploy_randomness_service.ps1" in workflow
    assert "superfly/flyctl-actions/setup-flyctl" in workflow
    assert "flyctl secrets import" in deploy_script
    assert "flyctl scale count" in deploy_script
    assert "flyctl deploy" in deploy_script


def test_deployment_workflow_does_not_trace_or_print_production_secrets():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for secret_name in (
        "FLY_BEARER_TOKEN",
        "QUANTUM_MANIFEST_SIGNING_KEY",
        "IBM_CLOUD_API_KEY",
        "IBM_QUANTUM_INSTANCE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "FLY_API_TOKEN",
    ):
        assert f"secrets.{secret_name}" in workflow or secret_name not in {
            "FLY_BEARER_TOKEN",
            "QUANTUM_MANIFEST_SIGNING_KEY",
        }

    assert "set -x" not in workflow
    assert "Set-PSDebug -Trace" not in workflow
    assert "echo ${{ secrets." not in workflow
    assert "Write-Host $env:" not in workflow
    assert "cat $" not in workflow


def test_deployment_workflow_smoke_tests_public_and_protected_contract():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for endpoint in ("/health", "/setup", "/openapi.json", "/docs"):
        assert endpoint in workflow
    assert "--proto '=https'" in workflow
    assert "--tlsv1.2" in workflow
    assert "OpenAPI 3.1" in workflow
    assert 'contract.get("openapi") != "3.1.0"' in workflow
    assert "Operator setup and verification" in workflow
    assert "/v1/bytes?n=1" in workflow
    assert "401" in workflow
    assert "FLY_BEARER_TOKEN:-" in workflow
    assert "skipped" in workflow.lower()


def test_local_production_deployment_is_rejected_and_docs_define_environment_setup():
    deploy_script = (WORKFLOW.parents[2] / "tools" / "deploy_randomness_service.ps1").read_text(
        encoding="utf-8"
    )
    documentation = (WORKFLOW.parents[2] / "docs" / "randomness-service.md").read_text(
        encoding="utf-8"
    )

    assert '$env:GITHUB_ACTIONS -ne "true"' in deploy_script
    for marker in (
        "Environment with required reviewers",
        "FLY_API_TOKEN",
        "FLY_BEARER_TOKEN",
        "QUANTUM_MANIFEST_SIGNING_KEY",
        "known-good commit",
        "Local production deployment is not a supported path",
    ):
        assert marker in documentation