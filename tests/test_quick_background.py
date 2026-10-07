from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.gui import app as gui_app  # noqa: F401
from curvemole.gui.dialogs import AddComponentDialog
from curvemole.gui.main_window import MainWindow


def test_add_choices_do_not_change_quick_add_options(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "separate-add.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Background quick add")
    curve = Curve("spectrum", np.linspace(-5, 5, 101), np.exp(-np.linspace(-5, 5, 101) ** 2))
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)

    def accept_background_points(dialog):
        dialog.function.setCurrentIndex(dialog.function.findData("gaussian"))
        dialog.add_as_background.setChecked(True)
        dialog.manual_points.setChecked(True)
        return dialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(AddComponentDialog, "exec", accept_background_points)
        window.add_component()
        assert window._pending_component.is_background
        assert window._pending_manual_points
        assert not window.quick_add_background.isChecked()
        assert not window.quick_add_manual_points.isChecked()
        window.plot_workspace.cancel_placement()
        window.quick_peak()
        assert not window._pending_component.is_background
        assert not window._pending_manual_points
        window._graphical_peak_placed(0.0, 1.0, 1.0)
        assert not project.model_for(curve.id).components[-1].is_background
        window.plot_workspace.cancel_placement()

        window.quick_add_background.setChecked(True)
        window.quick_add_manual_points.setChecked(True)

        def accept_plain(dialog):
            dialog.function.setCurrentIndex(dialog.function.findData("gaussian"))
            dialog.add_as_background.setChecked(False)
            dialog.manual_points.setChecked(False)
            return dialog.DialogCode.Accepted

        monkeypatch.setattr(AddComponentDialog, "exec", accept_plain)
        window.add_component()
        assert not window._pending_component.is_background
        assert not window._pending_manual_points
        assert window.quick_add_background.isChecked()
        assert window.quick_add_manual_points.isChecked()
        window.plot_workspace.cancel_placement()
        window.quick_peak()
        assert window._pending_component.is_background
        assert window._pending_manual_points
    finally:
        window.plot_workspace.cancel_placement()
        project.dirty = False
        window.close()
        app.processEvents()
