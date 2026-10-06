"""Saved-analysis selector and an actionable empty state for the model panel."""

from html import escape

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QComboBox, QLabel, QMenu, QWidgetAction

from curvemole.core.analysis_errors import DISPLAY_METHODS, available_methods, display_method


class UncertaintyDisplaySelector(QComboBox):
    analysisRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName(self.tr("Displayed uncertainty"))
        self._description = self.tr(
            "Choose one uncertainty method for every spectrum in this project. "
            "Spectra without that analysis show no analysis error. "
            "The original fit ±1σ remains visible. Outdated results are labelled Recorded.")
        self.setToolTip(self._description)
        self._has_analysis = False
        self.curve_id = None
        self.empty_menu = QMenu(self)
        action = QWidgetAction(self.empty_menu)
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
        action.setDefaultWidget(self.empty_message)
        self.empty_menu.addAction(action)

    def set_context(self, project, curve_id):
        self.curve_id = curve_id
        self.empty_menu.hide()
        self.blockSignals(True)
        try:
            self.clear()
            available = available_methods(project) if project is not None else ()
            for method, label in DISPLAY_METHODS.items():
                if method in available:
                    self.addItem(self.tr(label), method)
            self._has_analysis = self.count() > 0
            if not self._has_analysis:
                self.addItem(self.tr("No analysis available…"), "")
            chosen = display_method(project) if project is not None else None
            self.setCurrentIndex(max(0, self.findData(chosen or "")))
            self.setEnabled(project is not None)
        finally:
            self.blockSignals(False)

    def showPopup(self):
        if not self.isEnabled():
            return
        if self._has_analysis:
            super().showPopup()
        else:
            self.empty_menu.popup(self.mapToGlobal(QPoint(0, self.height())))

    def hidePopup(self):
        self.empty_menu.hide()
        super().hidePopup()

    def _open_analysis(self, _link):
        self.empty_menu.hide()
        self.analysisRequested.emit()
