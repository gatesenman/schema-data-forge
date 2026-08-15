"""PyInstaller entry point for the desktop app."""

import multiprocessing
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

from schema_data_forge.desktop import main  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
