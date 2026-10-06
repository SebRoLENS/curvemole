"""Saved-analysis selector and an actionable empty state for the model panel."""

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QLabel, QMenu, QWidgetAction

from curvemole.core.analysis_errors import DISPLAY_METHODS, available_methods, display_method


class UncertaintyDisplayMenu(QMenu):
    analysisRequested = Signal()
    methodSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(self.tr("Displayed uncertainty"))
        self._description = self.tr(
            "Choose one uncertainty method for every spectrum in this project. "
            "Spectra without that analysis show no analysis error. "
            "The original fit ±1σ remains visible. Outdated results are labelled Recorded.")
        self.setToolTip(self._description)
        self.current_method = None
        self.method_actions = {}
        self.action_group = QActionGroup(self)
        self.action_group.setExclusive(True)
        self.curve_id = None
        self.empty_action = QWidgetAction(self)
        self.empty_message = QLabel(
            escape(self.tr("To see the analysis error, first run an analysis in its panel."))
            + '<br><br><a href="uncertainty">'
            + escape(self.tr("Open Uncertainty Analysis")) + '</a>')
        self.empty_message.setWordWrap(True)
        self.empty_message.setMargin(12)
        self.empty_message.setMinimumWidth(260)
        self.empty_message.setMaximumWidth(340)
        self.empty_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.empty_message.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.empty_message.linkActivated.connect(self._open_analysis)
        self.empty_action.setDefaultWidget(self.empty_message)

    def set_context(self, project, curve_id):
        self.curve_id = curve_id
        self.hide()
        self.removeAction(self.empty_action)
        for action in self.method_actions.values():
            self.removeAction(action)
            self.action_group.removeAction(action)
            action.deleteLater()
        self.method_actions.clear()
        available = available_methods(project) if project is not None else ()
        self.current_method = display_method(project) if project is not None else None
        for method, label in DISPLAY_METHODS.items():
            if method in available or (available and method == self.current_method):
                title = self.tr(label)
                if method not in available:
                    title += self.tr(" (no recorded result)")
                action = self.addAction(title)
                action.setData(method)
                action.setCheckable(True)
                action.setEnabled(method in available)
                self.action_group.addAction(action)
                action.setChecked(method == self.current_method)
                action.triggered.connect(lambda checked=False, name=method: self.methodSelected.emit(name))
                self.method_actions[method] = action
        if not self.method_actions:
            self.addAction(self.empty_action)
        self.setEnabled(project is not None)

    def _open_analysis(self, _link):
        self.hide()
        self.analysisRequested.emit()
