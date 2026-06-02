"""TDD tests for BFX-20260531-orion-portrait-gitignore.

RED phase: all tests MUST fail before the fix is applied.
GREEN phase: all tests pass after the fix.

Acceptance Criteria verified:
  AC1  output/ (bare) does NOT appear as a gitignore pattern
  AC2  output/quantum_walk_*.html (or equivalent pattern) IS gitignored
  AC3  output/images/.gitkeep exists so the directory is tracked
  AC4  output/images/ path is not covered by any gitignore rule that
       would exclude it (i.e., no line that blanket-ignores output/)
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GITIGNORE = _REPO_ROOT / ".gitignore"
_GITKEEP = _REPO_ROOT / "output" / "images" / ".gitkeep"


def _gitignore_lines() -> list[str]:
    """Return non-blank, non-comment lines from .gitignore."""
    text = _GITIGNORE.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# AC1 — bare 'output/' entry must NOT be present
# ---------------------------------------------------------------------------
class TestNoBareOutputRule:
    def test_output_bare_not_in_gitignore(self):
        """The blanket 'output/' rule must be removed."""
        lines = _gitignore_lines()
        assert "output/" not in lines, (
            "Found bare 'output/' in .gitignore — this ignores output/images/ too. "
            "Replace it with specific patterns (e.g. output/quantum_walk_*.html)."
        )


# ---------------------------------------------------------------------------
# AC2 — quantum_walk HTML outputs ARE still gitignored
# ---------------------------------------------------------------------------
class TestQuantumWalkHtmlIgnored:
    def test_quantum_walk_pattern_present(self):
        """A pattern covering quantum_walk HTML files must exist."""
        lines = _gitignore_lines()
        has_pattern = any(
            ("quantum_walk" in line and ".html" in line)
            or line in ("output/*.html", "output/**/*.html")
            for line in lines
        )
        assert has_pattern, (
            "No gitignore pattern found for quantum_walk HTML files. "
            "Expected something like 'output/quantum_walk_*.html' or 'output/*.html'."
        )


# ---------------------------------------------------------------------------
# AC3 — output/images/.gitkeep exists
# ---------------------------------------------------------------------------
class TestGitkeepExists:
    def test_gitkeep_file_exists(self):
        """output/images/.gitkeep must exist so the directory is tracked."""
        assert _GITKEEP.exists(), (
            f"{_GITKEEP} does not exist. "
            "Create an empty .gitkeep so output/images/ is committed."
        )


# ---------------------------------------------------------------------------
# AC4 — no rule in .gitignore covers output/images/ path
# ---------------------------------------------------------------------------
class TestImagesNotIgnored:
    def test_no_rule_covers_output_images(self):
        """No gitignore rule should blanket-exclude output/images/."""
        lines = _gitignore_lines()
        blocking_rules = [
            line for line in lines
            if line in ("output/", "output/**", "output/*")
        ]
        assert not blocking_rules, (
            f"Found gitignore rules that block output/images/: {blocking_rules}. "
            "Remove them and use specific patterns instead."
        )
