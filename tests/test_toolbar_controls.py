from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow


def test_toolbar_actions_icons_and_explicit_mask_toggle():
    app = QApplication.instance() or QApplication([])
    project = Project()
    project.add_curve(Curve("test", [0, 1, 2], [0, 1, 0]))
    window = CurveMoleMainWindow(project)
    toolbar = window.findChild(QToolBar, "Main_toolbar")
    assert window.export_action not in toolbar.actions()
    assert any(window.export_action in action.menu().actions()
               for action in window.menuBar().actions() if action.menu())
    actions = (window.auto_axes_action, window.plot_workspace.view_active_action,
               window.background_subtracted_view_action, window.revert_background_action,
               window.plot_workspace.mask_action, window.import_action,
               window.open_action, window.save_action, window.undo_action,
               window.redo_action, window.calculator_action,
               window.add_component_action, window.quick_peak_action,
               window.fit_action, window.quick_fit_action, window.cancel_action,
               window.subtract_background_action)
    for action in actions:
        assert action in toolbar.actions()
        assert not action.icon().isNull()
        assert not action.icon().pixmap(40, 40).isNull()
        button = toolbar.widgetForAction(action)
        assert isinstance(button, QToolButton)
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert window.background_subtracted_view_action.isCheckable()
    original_palette = app.palette()
    light_palette = QPalette(original_palette)
    light_palette.setColor(QPalette.ColorRole.Button, Qt.GlobalColor.white)
    app.setPalette(light_palette)
    light = window.fit_action.icon().pixmap(64, 64).toImage()
    dark_palette = QPalette(original_palette)
    dark_palette.setColor(QPalette.ColorRole.Button, Qt.GlobalColor.black)
    app.setPalette(dark_palette)
    dark = window.fit_action.icon().pixmap(64, 64).toImage()
    assert dark != light
    # Axes stay visible on a dark toolbar.
    assert dark.pixelColor(7, 40).lightness() > 200
    disabled = window.fit_action.icon().pixmap(64, 64, QIcon.Mode.Disabled).toImage()
    assert disabled != dark
    mask = window.plot_workspace.mask_action.icon()
    assert mask.pixmap(64, 64, QIcon.Mode.Normal, QIcon.State.On).toImage() != (
        mask.pixmap(64, 64, QIcon.Mode.Normal, QIcon.State.Off).toImage()
    )
    app.setPalette(light_palette)
    assert window.fit_action.icon().pixmap(64, 64).toImage() == light
    app.setPalette(original_palette)
    workspace = window.plot_workspace
    assert not workspace.view_box.mask_mode
    workspace.mask_action.trigger()
    assert workspace.view_box.mask_mode
    workspace.mask_action.trigger()
    assert not workspace.view_box.mask_mode
    assert not hasattr(workspace, "mask_operation")
    window.project.dirty = False
    window.close()
    app.processEvents()
