"""DiagnosticsPanel."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.diagnostics import residual_diagnostics


class DiagnosticsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)
        self._last_residual = None
        self._diagnostic_text = ""

    def set_residual(self, residual: np.ndarray | None, *, indices=None, x=None,
                     historical: bool = False, standardized: bool = False) -> None:
        if residual is None:
            self._last_residual = None
            self._diagnostic_text = ""
            self.summary.setPlainText(self.tr("No fitted residuals are available."))
            return
        if residual is not self._last_residual:
            values = residual_diagnostics(residual, indices=indices, x=x).summary()
            self._diagnostic_text = "\n".join(f"{key}: {value}" for key, value in values.items())
            self._last_residual = residual
        status = self.tr("Historical fit: the current spectrum or model no longer matches.") if historical else ""
        units = self.tr("Residuals standardized by recorded point errors") if standardized else self.tr("Raw residuals")
        text = "\n".join(line for line in (status, units, self._diagnostic_text) if line)
        if text != self.summary.toPlainText():
            self.summary.setPlainText(text)

