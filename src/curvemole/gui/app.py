"""Desktop entry point."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from curvemole.gui.main_window import MainWindow
from curvemole.gui.updates import UpdateController
from curvemole.version import __version__


def _missing_toolbar_icons(window: MainWindow) -> list[str]:
    """Return bundled toolbar resources that failed to load."""
    actions = {
        "open-project.svg": window.open_action,
        "save-project.svg": window.save_action,
        "calculator.png": window.calculator_action,
        "subtract-background.png": window.subtract_background_action,
        "add-peak.png": window.add_component_action,
        "quick-add-peak.png": window.quick_peak_action,
        "fit.png": window.fit_action,
        "quick-fit.png": window.quick_fit_action,
    }
    return [name for name, action in actions.items() if action.icon().isNull()]


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
    window._release_update_controller = UpdateController(window)
    window.show()
    if os.environ.get("CURVEMOLE_SMOKE_TEST") == "1":
        from PySide6.QtCore import QTimer

        missing_icons = _missing_toolbar_icons(window)
        if missing_icons:
            raise RuntimeError(f"Missing bundled toolbar icons: {', '.join(missing_icons)}")
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
