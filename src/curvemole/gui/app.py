"""Desktop entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from curvemole.gui.main_window import MainWindow
from curvemole.version import __version__


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(arguments)
    QCoreApplication.setOrganizationName("CurveMole")
    QCoreApplication.setApplicationName("CurveMole")
    QCoreApplication.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    if os.environ.get("CURVEMOLE_SMOKE_TEST") == "1":
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, app.quit)
    if len(arguments) > 1:
        path = Path(arguments[1])
        if path.suffix.lower() == ".fitproj" and path.exists():
            window.open_project(path)
        elif path.exists():
            window.import_data([str(path)])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
