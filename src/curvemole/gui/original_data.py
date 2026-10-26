"""Direct access to the existing, undoable original-data restoration."""
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolBar, QToolButton

from curvemole.gui.main_window import _resource_icon


class OriginalDataController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.menu = QMenu(window)
        self.menu.setToolTipsVisible(True)
        self.action = QAction(_resource_icon("restore-original.svg"), self.tr("Restore original data"), window)
        self.action.setObjectName("restore_original_action")
        self.action.setToolTip(self.tr(
            "Restore original data\nRestore the active spectrum, highlighted spectra or a chosen group "
            "to their imported data. Recorded operations are removed; Undo remains available.\n"
            "View options changes the display only."
        ))
        self.action.setMenu(self.menu)
        window.restore_original_action = self.action
        window.restore_original_controller = self
        self.menu.aboutToShow.connect(self.rebuild_menu)
        toolbar = window.findChild(QToolBar, "Main_toolbar")
        if toolbar is not None:
            actions = toolbar.actions()
            index = actions.index(window.view_options_action) + 1
            toolbar.insertAction(actions[index] if index < len(actions) else None, self.action)
            button = toolbar.widgetForAction(self.action)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.rebuild_menu()
        self.sync()

    def sync(self):
        self.action.setEnabled(bool(self.window.project.curves) and not self.window.project.read_only)

    def rebuild_menu(self):
        self.menu.clear()
        self.menu.addSection(self.tr("Restore original data"))
        selected = self.window.curve_tree.selected_curve_ids()
        scopes = (
            (self.tr("Active spectrum"), 0, bool(self.window.active_curve_id)),
            (self.tr("Selected spectra ({count})").format(count=len(selected)), "selected", bool(selected)),
            (self.tr("Choose multiple spectra…"), 1, bool(self.window.project.curves)),
        )
        self.scope_actions = {}
        for label, scope, enabled in scopes:
            action = self.menu.addAction(label)
            action.setEnabled(enabled and not self.window.project.read_only)
            action.setToolTip(self.tr("Restore the original imported data. This action can be undone."))
            action.triggered.connect(lambda checked=False, target=scope: self.restore(target))
            self.scope_actions[scope] = action

    def restore(self, scope):
        self.window.apply_calculator({"restore": True, "scope": scope})
