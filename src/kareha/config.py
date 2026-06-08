"""
Configuration loader for Kareha Python.

Usage (typical board setup):

    from kareha.config import load_config

    cfg = load_config("config.py", mode="imageboard")   # explicit override; omit mode= to use BOARD_MODE from the file (hybrid)

The user's config.py is exec'd with access to all defaults; any uppercase
name they assign overrides the default.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from . import config_defaults


def load_config(user_config_path: str | Path | None = None, mode: str | None = None) -> dict[str, Any]:
    """
    Load configuration (hybrid mode support).

    - Starts with all values from config_defaults (including default BOARD_MODE).
    - If user_config_path is given (or ./config.py), exec it and let it override.
      The user's config.py may set BOARD_MODE = "blog" (or "textboard", etc.).
    - The effective mode is chosen with this priority:
        1. Explicit `mode` argument passed to load_config / make_app / CLI --mode (override)
        2. BOARD_MODE value from the user's config.py (if present)
        3. "imageboard" default
    - Aliases are normalized ("image" → "imageboard", "text"/"message" → "textboard").
    - Then applies mode-specific tweaks via apply_mode_defaults.
    - The final canonical value is stored in cfg["BOARD_MODE"].
    """
    cfg: dict[str, Any] = config_defaults.get_defaults_dict()

    # Load user overrides if present
    if user_config_path is None:
        candidate = Path("config.py")
        if candidate.exists():
            user_config_path = candidate

    if user_config_path:
        path = Path(user_config_path).resolve()
        spec = importlib.util.spec_from_file_location("_kareha_user_config", path)
        if spec and spec.loader:
            user_mod = importlib.util.module_from_spec(spec)
            # Give the user module the same globals as defaults for 'use constant' style
            # They can just do: ADMIN_PASS = "foo"
            user_mod.__dict__.update({k: v for k, v in config_defaults.__dict__.items() if k.isupper()})
            spec.loader.exec_module(user_mod)
            for k in dir(user_mod):
                if k.isupper() and not k.startswith("_"):
                    cfg[k] = getattr(user_mod, k)
            # Debug for capped trips etc.
            if "CAPPED_TRIPS" in cfg:
                print(f"[CONFIG LOAD] CAPPED_TRIPS loaded as: {cfg['CAPPED_TRIPS']}")

    # === Hybrid mode selection ===
    # Explicit arg (CLI or make_app call) wins as an override.
    # Otherwise fall back to whatever the user put in their config.py (BOARD_MODE),
    # or the default.
    if mode is not None:
        effective_mode = mode
    else:
        effective_mode = cfg.get("BOARD_MODE") or "imageboard"

    # Normalize aliases to canonical internal values ("imageboard", "textboard", "blog")
    _m = (effective_mode or "imageboard").lower().strip()
    if _m in ("image", "imageboard"):
        board_mode = "imageboard"
    elif _m in ("message", "text", "textboard"):
        board_mode = "textboard"
    elif _m == "blog":
        board_mode = "blog"
    else:
        board_mode = "imageboard"

    cfg["BOARD_MODE"] = board_mode

    # Mode adjustments (may override some things the user set, or fill gaps).
    # We pass the canonical board_mode.
    config_defaults.apply_mode_defaults(board_mode, cfg)

    # Basic validation
    if not cfg.get("ADMIN_PASS") or cfg["ADMIN_PASS"] == "CHANGEME":
        print("WARNING: ADMIN_PASS is still the default value. This is insecure!", file=sys.stderr)
    if not cfg.get("SECRET") or cfg["SECRET"] == "CHANGEME":
        print("WARNING: SECRET is still the default value. Change it!", file=sys.stderr)

    # Make available to post_stuff / other modules that don't receive the cfg object directly
    # (the main path is via wsgi.make_app setting it on the module)
    this_module = sys.modules[__name__]
    this_module.current_config = make_config_object(cfg)

    return cfg


def make_config_object(cfg_dict: dict[str, Any]) -> Any:
    """Return a simple object with attributes for the config (read-only view)."""
    class _Cfg:
        def __init__(self, d):
            self._d = d
        def __getattr__(self, name):
            if name in self._d:
                return self._d[name]
            raise AttributeError(name)
        def __repr__(self):
            return f"BoardConfig(mode={self._d.get('BOARD_MODE')})"
    return _Cfg(cfg_dict)
