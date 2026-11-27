"""Clean access to the presets catalog without sys.path mutations."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_CACHED_MOD: ModuleType | None = None


def get_presets_module() -> ModuleType:
    """Return the active ``presets`` module (reusing legacy import if loaded)."""
    global _CACHED_MOD
    existing = sys.modules.get("presets")
    if existing is not None:
        return existing
    if _CACHED_MOD is not None:
        return _CACHED_MOD
    try:
        _CACHED_MOD = importlib.import_module("presets")
        return _CACHED_MOD
    except ModuleNotFoundError:
        pass

    bot_presets = Path(__file__).resolve().parents[3] / "bot" / "presets.py"
    if not bot_presets.is_file():
        raise ModuleNotFoundError(f"Catalogue presets introuvable : {bot_presets}")
    spec = importlib.util.spec_from_file_location("presets", bot_presets)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Impossible de charger le module presets : {bot_presets}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["presets"] = module
    spec.loader.exec_module(module)
    _CACHED_MOD = module
    return module
