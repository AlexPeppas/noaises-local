"""Build noaises with PyInstaller.

Usage:
    uv run python packaging/build.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = REPO_ROOT / "packaging" / "noaises.spec"


def main():
    if not SPEC_FILE.exists():
        print(f"Error: spec file not found at {SPEC_FILE}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(SPEC_FILE),
    ]

    print("Building noaises...")
    print(f"  Spec: {SPEC_FILE}")
    print(f"  Python: {sys.executable}")
    print()

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    dist_dir = REPO_ROOT / "dist" / "noaises"
    print(f"\nBuild complete! Output: {dist_dir}")

    if sys.platform == "win32":
        print(f"  Executable: {dist_dir / 'noaises.exe'}")
    elif sys.platform == "darwin":
        print(f"  App bundle: {REPO_ROOT / 'dist' / 'noaises.app'}")
    else:
        print(f"  Executable: {dist_dir / 'noaises'}")


if __name__ == "__main__":
    main()
