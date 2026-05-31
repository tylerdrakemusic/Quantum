"""Orion portrait generator — run-state-aware AI portrait for the Benchmark Dashboard.

Generates a half-body portrait of "Orion" (the Quantum AI persona) using
DALL-E 3 → HuggingFace FLUX.1 → HF Spaces → Pollinations → SVG silhouette fallback.

Orion has three run-state modes driven by the most recent successful benchmark in
quantumpsi.db:
    - idle         : no successful run in last 7 days (lab study scene, ambient glow)
    - active       : last successful run 1–7 days ago (workstation, green monitors)
    - result_ready : last successful run within 24 hours (satisfied, bright displays)

Portrait is cached per calendar-date + mode so it is generated at most once per
day per mode. Up to 3 dated portraits are kept; older ones are pruned automatically.

Usage::

    from src.utils.orion_portrait import get_daily_portrait, get_portrait_img_tag

    path = get_daily_portrait()            # Path to cached PNG (or SVG fallback)
    tag  = get_portrait_img_tag(max_width=120)  # <img> data-URI tag
"""

from __future__ import annotations

import base64
import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Workspace integration path bootstrap
# ---------------------------------------------------------------------------
_WORKSPACE_ROOT = Path(r"f:\⊕Workspace")


def _load_workspace_module(module_key: str, relative: str):
    """Load a module from ⊕Workspace by file path, bypassing src namespace conflicts."""
    if module_key in sys.modules:
        return sys.modules[module_key]
    file_path = _WORKSPACE_ROOT / relative
    spec = importlib.util.spec_from_file_location(module_key, file_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        del sys.modules[module_key]
        return None
    return module


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_IMAGE_CACHE_DIR = _PROJECT_ROOT / "output" / "images"
_MAX_CACHED_PORTRAITS = 3

# ---------------------------------------------------------------------------
# Valid modes
# ---------------------------------------------------------------------------
_VALID_MODES = ("idle", "active", "result_ready")


# ---------------------------------------------------------------------------
# Run-state mode detection from quantumpsi.db
# ---------------------------------------------------------------------------

def _detect_mode() -> str:
    """Determine Orion's current run-state mode by reading quantumpsi.db.

    Checks the benchmarks table for the most recent successful run
    (defined as a row with non-null factor1 AND factor2).

    Returns
    -------
    str
        'result_ready' if last success was within 24 h,
        'active'       if last success was 1–7 days ago,
        'idle'         otherwise (or if DB is unavailable).
    """
    try:
        _utils_dir = str(Path(__file__).resolve().parent)
        if _utils_dir not in sys.path:
            sys.path.insert(0, _utils_dir)
        import init_db  # noqa: PLC0415

        conn = init_db.get_connection()
        row = conn.execute(
            "SELECT MAX(created_at) FROM benchmarks "
            "WHERE factor1 IS NOT NULL AND factor2 IS NOT NULL"
        ).fetchone()
        conn.close()
        if row and row[0]:
            last_run = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age = now - last_run
            if age <= timedelta(hours=24):
                return "result_ready"
            if age <= timedelta(days=7):
                return "active"
        return "idle"
    except Exception:
        return "idle"


# ---------------------------------------------------------------------------
# Fallback prompts (used when orion_config.db is unavailable)
# ---------------------------------------------------------------------------
_FALLBACK_PROMPTS: dict[str, str] = {
    "idle": (
        "A photorealistic half-body portrait of a brilliant, focused quantum physicist "
        "woman in her early 30s, waist up. Dark physics laboratory setting with holographic "
        "quantum circuit diagrams floating in the background. "
        "Deep indigo and purple rim lighting creating an ethereal glow around her. "
        "Wearing a dark fitted turtleneck, calm studious expression, studying holographic equations. "
        "Soft ambient indigo glow fills the dark lab. Confident, intelligent demeanour. "
        "Canon EOS 5D Mark IV, f/1.8, shallow depth of field, ultra-realistic RAW photo."
    ),
    "active": (
        "A photorealistic half-body portrait of a sharp, determined quantum physicist "
        "woman in her early 30s, waist up. Futuristic quantum computing workstation setting. "
        "Green circuit monitor displays glowing in the background, active computation visualisations. "
        "Deep indigo rim lighting, dark fitted turtleneck. "
        "Focused intense expression at work, hands near holographic controls. "
        "Professional, driven, highly capable. "
        "Canon EOS 5D Mark IV, f/1.8, shallow depth of field, ultra-realistic RAW photo."
    ),
    "result_ready": (
        "A photorealistic half-body portrait of a triumphant, satisfied quantum physicist "
        "woman in her early 30s, waist up. Bright holographic circuit displays showing "
        "successful quantum computation results in the background. "
        "Brilliant indigo and violet rim lighting illuminating a slight satisfied smile. "
        "Dark fitted turtleneck, confident composed expression of achievement. "
        "Bright successful results visible on quantum circuit monitors. "
        "Canon EOS 5D Mark IV, f/1.8, shallow depth of field, ultra-realistic RAW photo."
    ),
}

_NEGATIVE_PROMPT = (
    "illustration, painting, drawing, sketch, anime, manga, 3D render, CGI, "
    "digital art, concept art, fantasy, surreal, ugly, deformed, mutated, "
    "poorly drawn hands, extra limbs, missing limbs, painterly, watercolor, abstract, "
    "over-saturated, unnatural colors, garish, airbrushed, plastic skin, blurry, "
    "motion blur, text, watermark, signature, logo, jpeg artifacts, pixelated"
)

# Inline SVG fallback — quantum-themed silhouette with indigo/purple palette
_SVG_FALLBACK_B64 = base64.b64encode(
    b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 260" width="200" height="260">
  <rect width="200" height="260" fill="#080818"/>
  <circle cx="100" cy="70" r="38" fill="#1a0a3a"/>
  <circle cx="100" cy="70" r="40" fill="none" stroke="#4b0082" stroke-width="2" opacity="0.7"/>
  <ellipse cx="100" cy="190" rx="60" ry="72" fill="#1a0a3a"/>
  <line x1="72" y1="152" x2="128" y2="152" stroke="#6320EE" stroke-width="1.5" opacity="0.6"/>
  <line x1="65" y1="168" x2="135" y2="168" stroke="#6320EE" stroke-width="1" opacity="0.5"/>
  <line x1="78" y1="184" x2="122" y2="184" stroke="#6320EE" stroke-width="1" opacity="0.4"/>
  <circle cx="85" cy="152" r="2" fill="#a78bfa" opacity="0.8"/>
  <circle cx="115" cy="168" r="2" fill="#a78bfa" opacity="0.8"/>
  <ellipse cx="100" cy="190" rx="60" ry="72" fill="none" stroke="#4b0082" stroke-width="3" opacity="0.35"/>
  <text x="100" y="253" text-anchor="middle" fill="#a78bfa" font-size="12" font-family="monospace">Orion</text>
</svg>"""
).decode("ascii")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _today_cache_path(mode: str) -> Path:
    """Return the expected cache path for today's portrait given a mode."""
    today = date.today().isoformat()
    return _IMAGE_CACHE_DIR / f"orion_portrait_{mode}_{today}.png"


def _prune_old_portraits() -> None:
    """Keep only the _MAX_CACHED_PORTRAITS most recent Orion portrait files."""
    portraits = sorted(_IMAGE_CACHE_DIR.glob("orion_portrait_*.png"), reverse=True)
    for old in portraits[_MAX_CACHED_PORTRAITS:]:
        try:
            old.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Prompt builder (prefers orion_config.db, falls back to hardcoded prompts)
# ---------------------------------------------------------------------------

def _build_prompt(mode: str) -> tuple[str, str | None]:
    """Return (positive_prompt, negative_prompt) for the given mode.

    Prefers the active row in orion_config.db; falls back to built-in prompt.
    """
    try:
        import importlib.util as _ilu
        import sys as _sys

        _db_mod_key = "_orion_config_db"
        if _db_mod_key not in _sys.modules:
            _db_path = Path(__file__).resolve().parent / "orion_config_db.py"
            _spec = _ilu.spec_from_file_location(_db_mod_key, _db_path)
            if _spec and _spec.loader:
                _mod = _ilu.module_from_spec(_spec)
                _sys.modules[_db_mod_key] = _mod
                _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        _db_mod = _sys.modules.get(_db_mod_key)
        if _db_mod is not None:
            positive, negative = _db_mod.get_active_prompt(mode)
            return positive, negative
    except Exception:
        pass

    return _FALLBACK_PROMPTS.get(mode, _FALLBACK_PROMPTS["idle"]), _NEGATIVE_PROMPT


# ---------------------------------------------------------------------------
# Generation chain helpers
# ---------------------------------------------------------------------------

def _try_dalle3(prompt: str, save_dir: Path) -> Path | None:
    """Attempt to generate the portrait via DALL-E 3. Returns Path or None."""
    try:
        mod = _load_workspace_module(
            "_ws_dalle3_client",
            "src/integrations/dalle3/client.py",
        )
        if mod is None:
            return None
        client = mod.DallE3Client()
        path = client.generate_image(prompt, output_dir=save_dir, size="1024x1024")
        return path
    except Exception:
        return None


def _try_huggingface(
    prompt: str,
    save_dir: Path,
    negative_prompt: str | None = None,
) -> Path | None:
    """Attempt to generate the portrait via HuggingFace Inference. Returns Path or None."""
    try:
        mod = _load_workspace_module(
            "_ws_hf_image_client",
            "src/integrations/huggingface/client.py",
        )
        if mod is None:
            return None
        client = mod.HuggingFaceImageClient()
        try:
            path = client.generate_image(
                prompt,
                output_dir=save_dir,
                size="1024x1024",
                negative_prompt=negative_prompt,
            )
        except TypeError:
            path = client.generate_image(prompt, output_dir=save_dir, size="1024x1024")
        return path
    except Exception:
        return None


def _try_hf_spaces(prompt: str, save_dir: Path) -> Path | None:
    """Attempt to generate via HF Spaces FLUX.1-schnell (ZeroGPU). Returns Path or None."""
    try:
        mod = _load_workspace_module(
            "_ws_hf_spaces_client",
            "src/integrations/huggingface/spaces_client.py",
        )
        if mod is None:
            return None
        client = mod.HFSpacesImageClient()
        path = client.generate_image(prompt, output_dir=save_dir, width=1024, height=1024)
        return path
    except Exception:
        return None


def _try_pollinations(prompt: str, save_dir: Path) -> Path | None:
    """Attempt to generate via Pollinations.AI (free, no API key). Returns Path or None."""
    try:
        mod = _load_workspace_module(
            "_ws_pollinations_client",
            "src/integrations/pollinations/client.py",
        )
        if mod is None:
            return None
        client = mod.PollinationsClient()
        path = client.generate_image(prompt, output_dir=save_dir, width=1024, height=1024)
        return path
    except Exception:
        return None


def _svg_fallback_path(mode: str) -> Path:
    """Write inline SVG to a dated .svg file and return its path."""
    _IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    svg_path = _IMAGE_CACHE_DIR / f"orion_portrait_{mode}_{today}.svg"
    svg_data = base64.b64decode(_SVG_FALLBACK_B64)
    svg_path.write_bytes(svg_data)
    return svg_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_daily_portrait(mode: str | None = None) -> Path:
    """Return the path to today's Orion portrait.

    Generation cascade:
    1. Determine run-state mode (or use provided override).
    2. Return cached portrait if already generated today for this mode.
    3. Try DALL-E 3 (requires ``OPENAPI_TOKEN``).
    4. Fall back to HuggingFace Inference API (requires ``HF_TOKEN`` with credits).
    5. Try HuggingFace Spaces FLUX.1-schnell (free, ZeroGPU quota).
    6. Try Pollinations.AI (free, photorealistic, no API key required).
    7. Fall back to inline SVG silhouette (always succeeds).

    Parameters
    ----------
    mode:
        Override the run-state mode. If None, auto-detects from quantumpsi.db.

    Returns
    -------
    Path
        Absolute path to the portrait file. Never raises.
    """
    _IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if mode is None:
        mode = _detect_mode()

    today_path = _today_cache_path(mode)
    if today_path.exists():
        return today_path

    positive_prompt, negative_prompt = _build_prompt(mode)
    save_dir = _IMAGE_CACHE_DIR

    # 1. DALL-E 3 (primary)
    result = _try_dalle3(positive_prompt, save_dir)
    if result and result.exists():
        result.replace(today_path)
        _prune_old_portraits()
        return today_path

    # 2. HuggingFace Inference API
    result = _try_huggingface(positive_prompt, save_dir, negative_prompt=negative_prompt)
    if result and result.exists():
        result.replace(today_path)
        _prune_old_portraits()
        return today_path

    # 3. HuggingFace Spaces FLUX.1-schnell
    result = _try_hf_spaces(positive_prompt, save_dir)
    if result and result.exists():
        result.replace(today_path)
        _prune_old_portraits()
        return today_path

    # 4. Pollinations.AI
    result = _try_pollinations(positive_prompt, save_dir)
    if result and result.exists():
        result.replace(today_path)
        _prune_old_portraits()
        return today_path

    # 5. SVG silhouette fallback (always succeeds)
    return _svg_fallback_path(mode)


def get_portrait_img_tag(max_width: int = 160, mode: str | None = None) -> str:
    """Return an ``<img>`` HTML tag for Orion's portrait.

    Uses a data-URI so the HTML file is self-contained. Falls back to an
    inline SVG data-URI if the portrait is an SVG silhouette.

    Parameters
    ----------
    max_width:
        CSS max-width in pixels. Default: 160.
    mode:
        Override run-state mode. If None, auto-detects from quantumpsi.db.
    """
    if mode is None:
        mode = _detect_mode()

    portrait_path = get_daily_portrait(mode)
    suffix = portrait_path.suffix.lower()

    mode_labels = {
        "idle": "Idle",
        "active": "Active",
        "result_ready": "Result Ready",
    }
    mode_label = mode_labels.get(mode, mode)

    if suffix == ".png":
        mime = "image/png"
        data = base64.b64encode(portrait_path.read_bytes()).decode("ascii")
        src = f"data:{mime};base64,{data}"
    elif suffix == ".svg":
        src = f"data:image/svg+xml;base64,{_SVG_FALLBACK_B64}"
    else:
        src = f"data:image/svg+xml;base64,{_SVG_FALLBACK_B64}"

    return (
        f'<img src="{src}" alt="Orion — Quantum AI · {mode_label}" '
        f'id="orion-portrait" '
        f'style="max-width:{max_width}px; width:{max_width}px; height:{max_width}px; '
        f"object-fit:cover; border-radius:12px; "
        f"border:2px solid rgba(167,139,250,0.5); display:block; margin:0 auto; "
        f'cursor:pointer;" '
        f'title="Orion · {mode_label} · {date.today().isoformat()}" '
        f'onclick="document.getElementById(\'orion-edit-modal\').style.display=\'flex\'" />'
    )
