from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
GUIDANCE_FILES = (
    ROOT / "AGENT_STARTUP.md",
    ROOT / ".github" / "agents" / "⟨ψ⟩quantum-orchestrator.agent.md",
    ROOT / ".github" / "agents" / "⟨ψ⟩quantum-research.agent.md",
    ROOT / ".github" / "instructions" / "⟨ψ⟩quantum-base.instructions.md",
    ROOT / "README.md",
)


def _agent_frontmatter_pin_violations(agents_dir: Path) -> list[str]:
    violations: list[str] = []
    for agent_path in sorted(agents_dir.rglob("*.agent.md")):
        relative_path = agent_path.relative_to(agents_dir).as_posix()
        text = agent_path.read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.DOTALL)
        if frontmatter is None:
            violations.append(f"{relative_path}: missing YAML frontmatter")
            continue

        metadata = yaml.safe_load(frontmatter.group(1))
        if not isinstance(metadata, dict):
            violations.append(f"{relative_path}: YAML frontmatter must be a mapping")
            continue

        pinned_fields: list[str] = []
        for key in metadata:
            normalized_key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
            normalized_key = re.sub(r"[^A-Za-z0-9]+", "_", normalized_key).strip("_").casefold()
            key_parts = set(normalized_key.split("_"))
            if normalized_key in {"model", "provider"} or (
                "multiplier" in key_parts and bool({"model", "cost"} & key_parts)
            ):
                pinned_fields.append(normalized_key)

        if pinned_fields:
            violations.append(f"{relative_path}: {', '.join(pinned_fields)}")
    return violations


def test_agent_guidance_matches_live_paths_and_execution_policy() -> None:
    sys.path.insert(0, str(ROOT))
    from tools import fill_cache

    policy = json.loads((ROOT / "src" / "config" / "execution_policy.json").read_text(encoding="utf-8"))
    guidance = "\n".join(path.read_text(encoding="utf-8") for path in GUIDANCE_FILES)

    live_cache = fill_cache._LIVE_CACHE
    backup_dir = fill_cache._BACKUP_DIR
    assert live_cache == ROOT / "src" / "data" / "liveCache" / "ty_string_cache.txt"
    assert backup_dir == ROOT / "qbackups"
    assert live_cache.relative_to(ROOT).as_posix() in guidance
    assert "qbackups/" in guidance
    assert "src/data/qbackups" not in guidance
    assert "ignored" in guidance
    assert "operator-managed" in guidance
    assert "may be absent in a clean checkout" in guidance
    assert "verification reports unavailable" in guidance
    assert "C:\\G\\python.exe tools\\verify_cache.py" in guidance
    assert "secrets" in guidance
    assert "IBM_CLOUD_API_KEY" in guidance
    assert "IBM_QUANTUM_INSTANCE" in guidance
    assert "src/config/execution_policy.json" in guidance
    assert "src/quantum_toolkit" in guidance
    assert "src/quantum_rt.py" in guidance
    assert "src/core" not in guidance
    assert "TODO_AI.md" not in guidance
    assert "TODO_TYLER.md" not in guidance
    assert "PROJECT_PROFILE.json" not in guidance
    assert (ROOT / "docs" / "database-backup-inventory.md").exists()

    for target in re.findall(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)", (ROOT / "README.md").read_text(encoding="utf-8")):
        assert (ROOT / target).exists(), target

    monthly = policy["schedules"]
    assert "QuantumCacheFill_Monthly" in guidance
    assert "ShorsMonthlyBench" in guidance
    assert "VQEMonthlyBench" in guidance
    for policy_id, schedule in monthly.items():
        if schedule.get("schedule") == "daily":
            assert schedule["task_name"] in guidance
            assert schedule["time_utc"] in guidance
        else:
            expected = (
                f"day {schedule['day_of_month']} at "
                f"{schedule['hour']:02d}:{schedule['minute']:02d} UTC"
            )
            assert expected in guidance


def test_guidance_accepts_unavailable_cache_and_runtime_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.path.insert(0, str(ROOT))
    from src.utils import quantum_rt
    from tools import verify_cache

    missing_cache = tmp_path / "src" / "data" / "liveCache" / "ty_string_cache.txt"
    assert verify_cache.main(["--cache", str(missing_cache)]) == 2
    assert "cache verification unavailable" in capsys.readouterr().out

    monkeypatch.setattr(quantum_rt, "_find_cache_files", lambda: [])
    monkeypatch.setattr(quantum_rt, "_stream", None)
    assert len(quantum_rt.qRandomBitstring(32)) == 32
    assert quantum_rt.cache_integrity_status()["source"] == "secrets_fallback"


def test_agent_frontmatter_pin_scanner_detects_top_level_pins_and_allows_role_tiers(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    agent_path = agents_dir / "nested" / "example.agent.md"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        "---\n"
        "name: example\n"
        "role_tier: standard\n"
        "model_tier: balanced\n"
        "cost_tier: low\n"
        "model: pinned-model\n"
        "provider: pinned-provider\n"
        "model_multiplier: 1.5\n"
        "cost_multiplier: 2.0\n"
        "model_cost_multiplier: 1.25\n"
        "nested:\n"
        "  model: nested-value\n"
        "---\n"
        "Agent body.\n",
        encoding="utf-8",
    )

    assert _agent_frontmatter_pin_violations(agents_dir) == [
        "nested/example.agent.md: model, provider, model_multiplier, cost_multiplier, model_cost_multiplier"
    ]


def test_quantum_agent_definitions_have_no_model_or_cost_pins() -> None:
    agents_dir = ROOT / ".github" / "agents"
    assert any(agents_dir.rglob("*.agent.md")), "No agent definition files found"

    violations = _agent_frontmatter_pin_violations(agents_dir)

    assert not violations, "Forbidden agent frontmatter pins found:\n" + "\n".join(violations)