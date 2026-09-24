"""Readable uncertainty results with explicit, editable precision targets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.uncertainty_summary import METHOD_LABELS, summarize


class UncertaintyResults(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.method = "covariance"
        layout = QVBoxLayout(self)
        self.summary = QLabel("Run an analysis to inspect confidence intervals.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Spectrum", "Function", "Parameter", "Fit value", "Lower", "Upper",
            "Target ±", "Assessment",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(160)
        layout.addWidget(self.table)
        self.target_button = QPushButton("Set acceptable uncertainty for selected parameter…")
        self.target_button.clicked.connect(self._set_target)
        layout.addWidget(self.target_button)
        legend = QLabel(
            "OK: meets your absolute precision target with no flagged issue. Attention/Critical: "
            "hover over the assessment for its reasons. Not assessed: no precision target. Thresholds: |r| ≥0.95; "
            "interval ≥80% of bounded range. These are diagnostic heuristics, not scientific validation. "
            "Alternative minima are not tested automatically. "
            "200 replicates give a quick estimate; repeat with more for stable interval endpoints.")
        legend.setWordWrap(True)
        layout.addWidget(legend)
        toggle = QPushButton("Technical details")
        toggle.setCheckable(True)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(120)
        self.details.hide()
        toggle.toggled.connect(self.details.setVisible)
        layout.addWidget(toggle)
        layout.addWidget(self.details)

    def set_project(self, project):
        self.project = project
        self.refresh()

    def show_method(self, method):
        self.method = "parametric_monte_carlo" if method == "monte_carlo" else method
        self.refresh()

    def refresh(self):
        if self.project is None:
            return
        self.target_button.setEnabled(not self.project.read_only)
        record = self.project.results.get("uncertainty_reports", {}).get(self.method)
        self.table.setRowCount(0)
        if not record:
            self.summary.setText("No recorded result for this method. Run an analysis.")
            self.details.clear()
            return
        analysis, baseline = record["analysis"], record["baseline"]
        if hasattr(baseline, "to_dict"):
            baseline = baseline.to_dict(arrays=False)
        if hasattr(analysis, "to_dict"):
            analysis = analysis.to_dict()
        rows = summarize(self.project, baseline, analysis, self.method,
                         self.project.ui_state.get("uncertainty_targets", {}))
        confidence = analysis.get("confidence_level", baseline.get("settings", {}).get("confidence_level", .95))
        text = f"{METHOD_LABELS[self.method]} · {confidence:.1%} confidence"
        if "completed" in analysis:
            text += f" · {analysis['completed']}/{analysis['requested']} completed · {analysis['failed']} failed"
        elif self.method == "profile_likelihood":
            text += f" · {analysis['failed_points']} failed grid points"
        self.summary.setText(text)
        colors = {"OK": "#187541", "Attention": "#9b6500", "Critical": "#ba3030", "Not assessed": "#777777", "Fixed": "#777777"}
        for row, data in enumerate(rows):
            self.table.insertRow(row)
            for col, key in enumerate(("spectrum", "function", "parameter", "value", "lower", "upper", "target", "status")):
                value = data[key]
                label = "—" if value is None else f"{value:.8g}" if isinstance(value, float) else str(value)
                item = QTableWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, data["path"])
                item.setToolTip(data["reasons"] if col == 7 else data["path"])
                if col == 7:
                    item.setForeground(QColor(colors[data["status"]]))
                self.table.setItem(row, col, item)
        self.details.setPlainText(
            f"Method: {self.method}\nBaseline timestamp: {baseline.get('timestamp', '')}\n"
            f"Seed: {analysis.get('seed', 'not applicable')}\n"
            + "\n".join(f"{r['path']}: ({r['lower']}, {r['upper']})" for r in rows))

    def _set_target(self):
        if self.project is None or self.project.read_only or getattr(self.window(), "_thread", None) is not None:
            return
        row = self.table.currentRow()
        if row < 0:
            return
        path = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        targets = self.project.ui_state.setdefault("uncertainty_targets", {})
        value, accepted = QInputDialog.getDouble(
            self, "Acceptable absolute uncertainty", "Maximum distance from the fitted value to either interval endpoint.\n0 removes the target; use the parameter's units.",
            targets.get(path, 0), 0, 1e100, 10)
        if not accepted:
            return
        if value > 0:
            targets[path] = value
        else:
            targets.pop(path, None)
        self.project.touch()
        self.refresh()
