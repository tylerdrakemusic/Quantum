"""TDD tests for Orion AI persona portrait (FR-20260530-quantum-orion-persona).

RED phase: all tests MUST fail before implementation (ImportError or AssertionError).
GREEN phase: all tests pass after implementation.

Covers ACs:
  AC1  get_daily_portrait(mode) returns a valid Path for idle / active / result_ready
  AC2  seed_orion_config.py creates and seeds orion_config.db idempotently (3 mode rows)
  AC3  benchmark_dashboard.html shows Orion's portrait in the header area
  AC4  Dashboard has an "Edit Orion's Prompt" button per mode (modal)
  AC5  Portrait caching: at most once per calendar-date per mode; 3-portrait rolling window
  AC6  Fallback chain ends with SVG silhouette (always succeeds)
  AC7  This test file passes in full (pytest tests/test_orion_portrait.py)
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_WORKTREE = Path(__file__).resolve().parents[1]
_SRC_UTILS = _WORKTREE / "src" / "utils"
_TOOLS = _WORKTREE / "tools"

# Add to sys.path so internal imports inside the modules under test resolve.
for _p in [str(_WORKTREE), str(_SRC_UTILS), str(_TOOLS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _fresh_module(name: str, file: Path):
    """Load a module from *file* under an isolated *name* key.

    Each call creates a brand-new module object even if the same file has
    been loaded before, ensuring tests cannot pollute each other via shared
    module state.
    """
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# AC1 — get_daily_portrait returns a valid Path for all 3 modes
# ---------------------------------------------------------------------------
class TestGetDailyPortrait:
    """AC1: get_daily_portrait(mode) returns an existing Path for every mode."""

    @pytest.mark.parametrize("mode", ["idle", "active", "result_ready"])
    def test_returns_path_for_each_mode(self, tmp_path, monkeypatch, mode):
        mod = _fresh_module(f"_op_ac1_{mode}", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        result = mod.get_daily_portrait(mode)
        assert isinstance(result, Path), f"Expected Path, got {type(result)}"
        assert result.exists(), f"Portrait file does not exist: {result}"

    def test_cache_hit_does_not_regenerate(self, tmp_path, monkeypatch):
        """Calling get_daily_portrait twice for the same mode+date reuses the cache."""
        mod = _fresh_module("_op_ac1_cache", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        # Pre-populate a cache file
        today_path = mod._today_cache_path("idle")
        today_path.parent.mkdir(parents=True, exist_ok=True)
        today_path.write_bytes(b"FAKE_PNG")
        call_count = {"n": 0}
        original_dalle = mod._try_dalle3

        def _counting_dalle3(*a, **kw):
            call_count["n"] += 1
            return original_dalle(*a, **kw)

        monkeypatch.setattr(mod, "_try_dalle3", _counting_dalle3)
        result = mod.get_daily_portrait("idle")
        assert result == today_path
        assert call_count["n"] == 0, "Should not call DALL-E when cache file already exists"


# ---------------------------------------------------------------------------
# AC2 — seed_orion_config.py idempotent DB seeding
# ---------------------------------------------------------------------------
class TestSeedOrionConfig:
    """AC2: seed_orion_config.py creates orion_config.db with 3 active mode rows, idempotently."""

    def test_seed_creates_db(self, tmp_path, monkeypatch):
        mod = _fresh_module("_seed_ac2_a", _TOOLS / "seed_orion_config.py")
        db_path = tmp_path / "orion_config.db"
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        mod.seed()
        assert db_path.exists(), "orion_config.db should be created by seed()"

    def test_seed_creates_all_three_modes(self, tmp_path, monkeypatch):
        mod = _fresh_module("_seed_ac2_b", _TOOLS / "seed_orion_config.py")
        db_path = tmp_path / "orion_config.db"
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        mod.seed()
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT mode FROM orion_config WHERE active=1").fetchall()
        conn.close()
        modes = {r[0] for r in rows}
        assert modes == {"idle", "active", "result_ready"}, (
            f"Expected all 3 modes, got: {modes}"
        )

    def test_seed_is_idempotent_no_duplicate_rows(self, tmp_path, monkeypatch):
        mod = _fresh_module("_seed_ac2_c", _TOOLS / "seed_orion_config.py")
        db_path = tmp_path / "orion_config.db"
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        mod.seed()
        mod.seed()  # second call must not duplicate rows
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM orion_config WHERE active=1"
        ).fetchone()[0]
        conn.close()
        assert count == 3, (
            f"Expected exactly 3 active rows after two seed() calls, got {count}"
        )

    def test_seed_prompts_are_non_empty(self, tmp_path, monkeypatch):
        mod = _fresh_module("_seed_ac2_d", _TOOLS / "seed_orion_config.py")
        db_path = tmp_path / "orion_config.db"
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        mod.seed()
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT mode, positive_prompt FROM orion_config WHERE active=1"
        ).fetchall()
        conn.close()
        for row in rows:
            assert len(row[1]) > 20, f"Positive prompt too short for mode={row[0]!r}"


# ---------------------------------------------------------------------------
# AC5 — Portrait caching: at most once per day, 3-portrait rolling window
# ---------------------------------------------------------------------------
class TestPortraitCaching:
    """AC5: cache filename contains mode+date; _prune_old_portraits keeps at most 3."""

    def test_cache_filename_format(self, tmp_path, monkeypatch):
        from datetime import date
        mod = _fresh_module("_op_ac5_name", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        today = date.today().isoformat()
        cache_path = mod._today_cache_path("idle")
        assert cache_path.name.startswith("orion_portrait_"), (
            f"Expected 'orion_portrait_' prefix, got {cache_path.name!r}"
        )
        assert "idle" in cache_path.name, (
            f"Expected mode 'idle' in filename, got {cache_path.name!r}"
        )
        assert today in cache_path.name, (
            f"Expected today {today!r} in filename, got {cache_path.name!r}"
        )

    def test_prune_keeps_at_most_3_portraits(self, tmp_path, monkeypatch):
        mod = _fresh_module("_op_ac5_prune", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        # Create 5 portrait PNG files
        for i in range(5):
            (tmp_path / f"orion_portrait_idle_2026-05-{i + 1:02d}.png").write_bytes(b"\x89PNG")
        mod._prune_old_portraits()
        remaining = list(tmp_path.glob("orion_portrait_*.png"))
        assert len(remaining) <= 3, (
            f"Expected at most 3 portraits after prune, got {len(remaining)}"
        )

    def test_prune_retains_newest_files(self, tmp_path, monkeypatch):
        mod = _fresh_module("_op_ac5_newest", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        dates = [f"2026-05-{i:02d}" for i in range(1, 6)]
        for d in dates:
            (tmp_path / f"orion_portrait_idle_{d}.png").write_bytes(b"\x89PNG")
        mod._prune_old_portraits()
        remaining = sorted(
            p.name for p in tmp_path.glob("orion_portrait_*.png")
        )
        # Newest 3 dates should be retained (sorted descending, keep first 3)
        newest = sorted(dates, reverse=True)[:3]
        for d in newest:
            assert any(d in name for name in remaining), (
                f"Expected date {d!r} to be in retained portraits"
            )


# ---------------------------------------------------------------------------
# AC6 — Fallback chain: always succeeds with SVG silhouette
# ---------------------------------------------------------------------------
class TestFallbackChain:
    """AC6: when all external generators fail, SVG silhouette is returned."""

    def test_svg_fallback_when_all_apis_fail(self, tmp_path, monkeypatch):
        mod = _fresh_module("_op_ac6", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        monkeypatch.setattr(mod, "_try_dalle3", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_try_huggingface", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_try_hf_spaces", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_try_pollinations", lambda *a, **kw: None)
        result = mod.get_daily_portrait("idle")
        assert result.exists(), "SVG fallback file should exist"
        assert result.suffix in (".svg", ".png"), (
            f"Unexpected fallback extension: {result.suffix!r}"
        )

    def test_svg_fallback_content_is_valid_svg(self, tmp_path, monkeypatch):
        mod = _fresh_module("_op_ac6_svg", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        monkeypatch.setattr(mod, "_try_dalle3", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_try_huggingface", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_try_hf_spaces", lambda *a, **kw: None)
        monkeypatch.setattr(mod, "_try_pollinations", lambda *a, **kw: None)
        result = mod.get_daily_portrait("idle")
        if result.suffix == ".svg":
            content = result.read_text(encoding="utf-8")
            assert "<svg" in content, "SVG fallback must contain <svg element"


# ---------------------------------------------------------------------------
# AC3+AC4 — get_portrait_img_tag and Dashboard integration
# ---------------------------------------------------------------------------
class TestPortraitImgTag:
    """AC3: get_portrait_img_tag returns a valid <img> data-URI tag."""

    @pytest.mark.parametrize("mode", ["idle", "active", "result_ready"])
    def test_returns_img_tag(self, tmp_path, monkeypatch, mode):
        mod = _fresh_module(f"_op_tag_{mode}", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        tag = mod.get_portrait_img_tag(max_width=120, mode=mode)
        assert tag.startswith("<img"), f"Expected <img> tag, got: {tag[:60]!r}"
        assert "data:" in tag, "Expected data-URI in <img> src"
        assert "120" in tag, "Expected max_width=120 in tag"

    def test_img_tag_contains_orion_label(self, tmp_path, monkeypatch):
        mod = _fresh_module("_op_tag_label", _SRC_UTILS / "orion_portrait.py")
        monkeypatch.setattr(mod, "_IMAGE_CACHE_DIR", tmp_path)
        tag = mod.get_portrait_img_tag(max_width=80, mode="idle")
        assert "Orion" in tag, f"Expected 'Orion' label in img tag, got: {tag!r}"


class TestDashboardIntegration:
    """AC3+AC4: gen_benchmark_dashboard.py generate_html embeds Orion portrait and edit button."""

    def test_generate_html_contains_orion_portrait(self, tmp_path, monkeypatch):
        dash = _fresh_module("_gbd_portrait", _TOOLS / "gen_benchmark_dashboard.py")
        # Patch _get_orion_tag to avoid real portrait generation
        monkeypatch.setattr(
            dash, "_get_orion_tag",
            lambda mode=None: '<img id="orion-portrait-test" alt="Orion" />',
            raising=False,
        )
        html_out = dash.generate_html([], [], [], "2026-05-30T00:00:00Z", [], {})
        assert "orion" in html_out.lower(), (
            "Expected 'orion' somewhere in generated HTML"
        )

    def test_generate_html_contains_edit_button(self, tmp_path, monkeypatch):
        dash = _fresh_module("_gbd_edit", _TOOLS / "gen_benchmark_dashboard.py")
        monkeypatch.setattr(
            dash, "_get_orion_tag",
            lambda mode=None: "",
            raising=False,
        )
        html_out = dash.generate_html([], [], [], "2026-05-30T00:00:00Z", [], {})
        lower = html_out.lower()
        assert "orion" in lower, "Expected 'orion' in dashboard HTML"
        assert ("edit" in lower or "prompt" in lower), (
            "Expected edit/prompt button for Orion in dashboard HTML"
        )


# ---------------------------------------------------------------------------
# orion_config_db — get_active_prompt per mode
# ---------------------------------------------------------------------------
class TestOrionConfigDb:
    """orion_config_db: get_active_prompt(mode) returns (positive, negative | None)."""

    def _seeded_db(self, tmp_path) -> Path:
        """Helper: seed a temp orion_config.db and return its path."""
        seed = _fresh_module("_seed_cfgdb", _TOOLS / "seed_orion_config.py")
        db_path = tmp_path / "orion_config.db"
        seed._DB_PATH = db_path
        seed.seed()
        return db_path

    @pytest.mark.parametrize("mode", ["idle", "active", "result_ready"])
    def test_returns_strings_for_each_mode(self, tmp_path, monkeypatch, mode):
        db_path = self._seeded_db(tmp_path)
        mod = _fresh_module(f"_cfgdb_{mode}", _SRC_UTILS / "orion_config_db.py")
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        pos, neg = mod.get_active_prompt(mode)
        assert isinstance(pos, str) and len(pos) > 20, (
            f"positive_prompt too short for mode={mode!r}: {pos!r}"
        )
        assert neg is None or isinstance(neg, str), (
            f"negative_prompt should be None or str for mode={mode!r}"
        )

    def test_raises_for_missing_db(self, tmp_path, monkeypatch):
        mod = _fresh_module("_cfgdb_missing", _SRC_UTILS / "orion_config_db.py")
        monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "nonexistent.db")
        with pytest.raises(RuntimeError):
            mod.get_active_prompt("idle")

    def test_invalid_mode_raises_or_falls_back(self, tmp_path, monkeypatch):
        db_path = self._seeded_db(tmp_path)
        mod = _fresh_module("_cfgdb_invalid", _SRC_UTILS / "orion_config_db.py")
        monkeypatch.setattr(mod, "_DB_PATH", db_path)
        # Invalid mode should either raise RuntimeError or fall back gracefully
        try:
            pos, neg = mod.get_active_prompt("invalid_mode")
            # If it doesn't raise, the returned prompt should still be a non-empty string
            assert isinstance(pos, str) and len(pos) > 0
        except RuntimeError:
            pass  # Also acceptable
