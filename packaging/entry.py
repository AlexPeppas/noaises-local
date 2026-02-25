"""PyInstaller entry point — bootstraps the noaises package.

PyInstaller runs this as __main__, so we can't use relative imports
in main.py directly. This wrapper imports the package entry point.
"""

from noaises.main import main

if __name__ == "__main__":
    main()
