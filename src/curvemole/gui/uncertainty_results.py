"""Readable uncertainty results with click-through diagnostic assessments."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMessageBox,
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
        self.curve_id = None
        self.method = "covariance"
        layout = QVBoxLayout(self)
        self.summary = QLabel("Run an analysis to inspect confidence intervals.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Spectrum", "Function", "Parameter", "Fit value", "Lower", "Upper",
            "Assessment",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(160)
        self.table.cellClicked.connect(self._cell_clicked)
        layout.addWidget(self.table)
        legend = QLabel(
            "OK: no diagnostic issue was flagged. Attention/Critical: "
            "click the assessment for its reasons. Thresholds: |r| ≥0.95; "
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

    def set_project(self, project, curve_id=None):
        self.project = project
        self.curve_id = curve_id or (project.curves[0].id if len(project.curves) == 1 else None)
        self.refresh()

    def show_method(self, method):
        self.method = "parametric_monte_carlo" if method == "monte_carlo" else method
        self.refresh()

    def refresh(self):
        if self.project is None:
            return
        record = self.project.results.get("uncertainty_reports_by_curve", {}).get(self.curve_id, {}).get(self.method)
        if record is None:
            legacy = self.project.results.get("uncertainty_reports", {}).get(self.method)
            baseline = legacy.get("baseline", {}) if isinstance(legacy, dict) else {}
            if self.curve_id and any(path.startswith(self.curve_id + ".")
                                     for path in baseline.get("parameters", {})):
                record = legacy
        self.table.setRowCount(0)
        if not record:
            self.summary.setText("No recorded result for this spectrum and method. Run an analysis.")
            self.details.clear()
            return
        analysis, baseline = record["analysis"], record["baseline"]
        if hasattr(baseline, "to_dict"):
            baseline = baseline.to_dict(arrays=False)
        if hasattr(analysis, "to_dict"):
            analysis = analysis.to_dict()
        rows = summarize(self.project, baseline, analysis, self.method)
        rows = [row for row in rows if row["path"].startswith(self.curve_id + ".")]
        confidence = analysis.get("confidence_level", baseline.get("settings", {}).get("confidence_level", .95))
        text = f"{METHOD_LABELS[self.method]} · {confidence:.1%} confidence"
        if "completed" in analysis:
            text += f" · {analysis['completed']}/{analysis['requested']} completed · {analysis['failed']} failed"
        elif self.method == "profile_likelihood":
            text += f" · {analysis['failed_points']} failed grid points"
        self.summary.setText(text)
        colors = {"OK": "#187541", "Attention": "#9b6500", "Critical": "#ba3030", "Fixed": "#777777"}
        self._assessment_rows = rows
        for row, data in enumerate(rows):
            self.table.insertRow(row)
            for col, key in enumerate(("spectrum", "function", "parameter", "value", "lower", "upper", "status")):
                value = data[key]
                label = "—" if value is None else f"{value:.8g}" if isinstance(value, float) else str(value)
                item = QTableWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, data["path"])
                item.setToolTip(
                    "Click to see why this assessment was assigned." if col == 6 else data["path"])
                if col == 6:
                    item.setForeground(QColor(colors[data["status"]]))
                    font = QFont(item.font())
                    font.setUnderline(True)
                    item.setFont(font)
                self.table.setItem(row, col, item)
        self.details.setPlainText(
            f"Method: {self.method}\nBaseline timestamp: {baseline.get('timestamp', '')}\n"
            f"Seed: {analysis.get('seed', 'not applicable')}\n"
            + "\n".join(f"{r['path']}: ({r['lower']}, {r['upper']})" for r in rows))

    def _cell_clicked(self, row: int, column: int) -> None:
        if column != 6 or row >= len(getattr(self, "_assessment_rows", [])):
            return
        data = self._assessment_rows[row]
        reasons = data.get("reason_items") or ([data["reasons"]] if data["reasons"] else [])
        details = "".join(f"<li>{escape(reason)}</li>" for reason in reasons)
        box = QMessageBox(self)
        box.setWindowTitle("Assessment details")
        box.setText(escape(f"{data['spectrum']} / {data['function']} / {data['parameter']}: {data['status']}"))
        box.setInformativeText(f"<ul>{details}</ul>" if details else "No reasons were recorded.")
        box.exec()
