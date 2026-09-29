from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.gui import app as gui_app  # noqa: F401
from curvemole.gui.dialogs import AddComponentDialog
from curvemole.gui.main_window import MainWindow


def test_add_background_choice_is_reused_by_quick_add(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Background quick add")
    curve = Curve("spectrum", np.linspace(-5, 5, 101), np.exp(-np.linspace(-5, 5, 101) ** 2))
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)
    keys = ("quick_add/gaussian/background", "quick_add/gaussian/manual_points")
    previous = {key: window.settings.value(key) for key in keys}

    def accept_background(dialog):
        dialog.function.setCurrentIndex(dialog.function.findData("gaussian"))
        dialog.add_as_background.setChecked(True)
        dialog.manual_points.setChecked(False)
        return dialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(AddComponentDialog, "exec", accept_background)
        window.add_component()
        assert window._pending_component.is_background
        window.plot_workspace.cancel_placement()

        window.quick_function_selector.setCurrentIndex(
            window.quick_function_selector.findData("gaussian")
        )
        window.quick_peak()
        assert window._pending_component.is_background
        window._graphical_peak_placed(0.0, 1.0, 1.0)
        component = project.model_for(curve.id).components[-1]
        assert component.is_background
        window.model_panel.refresh(component.id)
        assert "Background" in window.model_panel.components.item(0).text()
        assert window.model_panel.components.item(0).font().bold()

        def accept_manual(dialog):
            dialog.function.setCurrentIndex(dialog.function.findData("gaussian"))
            dialog.add_as_background.setChecked(True)
            dialog.manual_points.setChecked(True)
            return dialog.DialogCode.Accepted

        monkeypatch.setattr(AddComponentDialog, "exec", accept_manual)
        window.add_component()
        window.plot_workspace.cancel_placement()
        window.quick_peak()
        assert window._pending_component.is_background
        assert window._pending_manual_points is True
    finally:
        window.plot_workspace.cancel_placement()
        for key, value in previous.items():
            if value is None:
                window.settings.remove(key)
            else:
                window.settings.setValue(key, value)
        project.dirty = False
        window.close()
        app.processEvents()
