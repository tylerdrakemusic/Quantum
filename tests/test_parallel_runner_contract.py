from pathlib import Path
import configparser
import importlib.util
import json
import shlex


def load_runner():
    runner_path = Path(__file__).parents[1] / "tools" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("run_tests", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def test_parallel_runner_contract_is_declared():
    policy = Path(__file__).parents[1] / "tools" / "parallel_test_policy.json"
    runner = Path(__file__).parents[1] / "tools" / "run_tests.py"

    assert policy.is_file()
    assert runner.is_file()


def test_build_command_composes_policy_exclusions_with_repository_marker_defaults():
    root = Path(__file__).parents[1]
    command = load_runner().build_command(parallel=False, junitxml=None)
    parallel_command = load_runner().build_command(parallel=True, junitxml=None)

    module_option = command.index("-m")
    marker_expression = command[command.index("-m", module_option + 1) + 1]
    policy = json.loads((root / "tools" / "parallel_test_policy.json").read_text(encoding="utf-8"))
    config = configparser.ConfigParser(interpolation=None)
    config.read(root / "pytest.ini", encoding="utf-8")
    addopts = shlex.split(config.get("pytest", "addopts", fallback=""))
    configured = addopts[addopts.index("-m") + 1] if "-m" in addopts else None

    assert all(f"not {marker}" in marker_expression for marker in policy["excluded_markers"])
    assert configured is None or configured in marker_expression
    parallel_module_option = parallel_command.index("-m")
    parallel_expression = parallel_command[parallel_command.index("-m", parallel_module_option + 1) + 1]
    assert parallel_expression == marker_expression


def test_main_propagates_worker_failure(monkeypatch):
    runner = load_runner()
    completed = type("Completed", (), {"returncode": 17})()
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: completed)
    monkeypatch.setattr(runner.sys, "argv", ["run_tests.py", "--parallel"])

    assert runner.main() == 17