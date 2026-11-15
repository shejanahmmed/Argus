"""Top-level module execution for `python -m argus`."""

import sys

from argus.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
