from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole.gui.main_window import MainWindow
from curvemole.version import __version__


def test_main_window_starts_offscreen() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle().endswith(f"CurveMole {__version__}")
    assert window.plot_workspace is not None
    window.close()
    app.processEvents()
