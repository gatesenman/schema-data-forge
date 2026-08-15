"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    """Start the Qt application and block until the window is closed."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Schema Data Forge")
    app.setOrganizationName("schema-data-forge")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
