"""Enable ``python -m omoikane`` and serve as the PyInstaller entry point."""
import sys

from omoikane.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
