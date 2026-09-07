from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from curvemole.gui.app import CurveMoleMainWindow


def test_toolbar_actions_icons_and_explicit_mask_toggle():
    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow()
    toolbar = window.findChild(QToolBar, "Main_toolbar")
    assert window.export_action not in toolbar.actions()
    assert any(window.export_action in action.menu().actions()
               for action in window.menuBar().actions() if action.menu())
    actions = (window.auto_axes_action, window.plot_workspace.view_active_action,
               window.background_subtracted_view_action, window.revert_background_action)
    for action in actions:
        assert action in toolbar.actions()
        assert not action.icon().isNull()
        assert not action.icon().pixmap(40, 40).isNull()
        button = toolbar.widgetForAction(action)
        assert isinstance(button, QToolButton)
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert window.background_subtracted_view_action.isCheckable()
    workspace = window.plot_workspace
    assert not workspace.view_box.mask_mode
    for operation in (0, 1):
        workspace.mask_operation.setCurrentIndex(operation)
        assert not workspace.view_box.mask_mode
        workspace.mask_toggle.click()
        assert workspace.view_box.mask_mode
        workspace.mask_toggle.click()
        assert not workspace.view_box.mask_mode
    window.project.dirty = False
    window.close()
    app.processEvents()
