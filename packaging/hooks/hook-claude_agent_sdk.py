"""PyInstaller hook for claude_agent_sdk — ensures bundled CLI is collected.

The SDK ships a bundled Claude Code CLI binary under
claude_agent_sdk/_bundled/. In frozen mode, the SDK's own
_find_bundled_cli() lookup breaks because __file__ points into the
PyInstaller archive. We collect the binary here so it's available at
<MEIPASS>/_bundled/, and resources.py provides the explicit cli_path
to bypass the broken lookup.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, get_package_paths

# Collect everything from the SDK (submodules, data, binaries)
datas, binaries, hiddenimports = collect_all("claude_agent_sdk")

# Explicitly ensure the _bundled directory is included
try:
    _, pkg_path = get_package_paths("claude_agent_sdk")
    bundled_dir = Path(pkg_path) / "_bundled"
    if bundled_dir.exists():
        for item in bundled_dir.iterdir():
            if item.is_file():
                datas.append((str(item), "_bundled"))
except Exception:
    pass
