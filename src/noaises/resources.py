"""Frozen-aware path resolution for PyInstaller bundles.

In dev mode, paths resolve relative to the repo root.
In frozen mode (PyInstaller), paths resolve relative to sys._MEIPASS.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def get_base_dir() -> Path:
    """Return the application base directory.

    Frozen: sys._MEIPASS (PyInstaller temp extraction dir)
    Dev:    repo root (three levels up from this file)
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


def get_config_dir() -> Path:
    """Path to the config/ directory (contains personality.toml etc.)."""
    return get_base_dir() / "config"


def get_surface_dir() -> Path:
    """Path to the surface/web/ directory (HTML/CSS/JS assets).

    Frozen: bundled under <MEIPASS>/noaises/surface/web/
    Dev:    src/noaises/surface/web/
    """
    if is_frozen():
        return get_base_dir() / "noaises" / "surface" / "web"
    return Path(__file__).resolve().parent / "surface" / "web"


def get_dotenv_path() -> Path:
    """Path to the .env file.

    Frozen: ~/.noaises/.env (user's data directory)
    Dev:    repo root .env
    """
    if is_frozen():
        return Path.home() / ".noaises" / ".env"
    return get_base_dir() / ".env"


def get_claude_cli_path() -> str | None:
    """Explicit path to the bundled claude CLI binary.

    Frozen: <MEIPASS>/_bundled/claude.exe (Windows) or claude (macOS)
    Dev:    None (let the SDK auto-discover via PATH)
    """
    if not is_frozen():
        return None

    base = get_base_dir()
    if sys.platform == "win32":
        cli = base / "_bundled" / "claude.exe"
    else:
        cli = base / "_bundled" / "claude"

    if cli.exists():
        return str(cli)

    # Fallback: let the SDK try its own discovery
    return None
