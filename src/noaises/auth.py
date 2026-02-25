"""Authentication check — API key or existing Claude Code OAuth session.

The Claude Agent SDK automatically uses Claude Code's OAuth credentials
when no ANTHROPIC_API_KEY is set. We just verify that one of these auth
methods is available before starting the companion.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .resources import get_claude_cli_path


def find_claude_cli() -> str | None:
    """Locate the system-installed Claude Code CLI for auth checks.

    Uses the user's system PATH install (where OAuth creds live),
    NOT the bundled CLI inside PyInstaller builds.
    """
    return shutil.which("claude")


def is_authenticated() -> bool:
    """Check whether we have valid credentials (API key or OAuth)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True

    cli = find_claude_cli()
    if not cli:
        return False

    try:
        result = subprocess.run(
            [cli, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def ensure_authenticated() -> None:
    """Verify authentication exists before starting the companion.

    Checks for API key or existing Claude Code OAuth session.
    The SDK handles the actual auth — we just fail fast with a
    clear message if neither is available.
    """
    if is_authenticated():
        return

    cli = find_claude_cli()
    if cli:
        print(
            "\n[auth] Not logged in. Please run this first:\n"
            f"  {cli} login\n"
        )
    else:
        print(
            "\n[auth] Authentication required. Options:\n"
            "  1. Install Claude Code and run 'claude login'\n"
            "  2. Set ANTHROPIC_API_KEY in your environment or ~/.noaises/.env\n"
        )
    sys.exit(1)
