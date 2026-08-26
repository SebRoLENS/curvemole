from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole.gui.main_window import MainWindow


def test_main_window_starts_offscreen() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle().endswith("CurveMole 0.1.0")
    assert window.plot_workspace is not None
    window.close()
    app.processEvents()
