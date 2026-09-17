"""Interactive, review-first removal of narrow cosmic-ray spikes."""

from __future__ import annotations

import copy

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import median_filter

OWNER = "org.curvemole.community.cosmic_ray_removal"
METADATA_KEY = "cosmic_ray_removal"


class Candidate:
    def __init__(self, start, end, score, source, replacement, accepted=True):
        self.start = int(start)
        self.end = int(end)
        self.score = float(score)
        self.source = str(source)
        self.replacement = np.asarray(replacement, dtype=float)
        self.accepted = bool(accepted)


def robust_z(values):
    values = np.asarray(values, dtype=float)
    center = np.median(values)
    mad = np.median(np.abs(values - center))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        scale = np.std(values)
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        return np.zeros_like(values)
    return (values - center) / scale


def _validate_xy(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) != len(y) or len(x) < 15 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("The spectrum needs at least 15 finite x/y points.")
    difference = np.diff(x)
    if not (np.all(difference > 0) or np.all(difference < 0)):
        raise ValueError("The x axis must be strictly monotonic.")
    return x, y


def interpolate_interval(x, y, start, end, support=4):
    """PCHIP repair from points immediately outside an inclusive interval."""
    x, y = _validate_xy(x, y)
    start, end = int(start), int(end)
    if not 0 <= start <= end < len(y):
        raise ValueError("Invalid candidate interval.")
    left = np.arange(max(0, start - support), start)
    right = np.arange(end + 1, min(len(y), end + 1 + support))
    if not len(left) or not len(right):
        raise ValueError("A correction needs unaffected points on both sides.")
    indexes = np.r_[left, right]
    if len(indexes) < 2:
        raise ValueError("Not enough surrounding points to repair this interval.")
    order = np.argsort(x[indexes])
    if len(indexes) >= 3:
        return np.asarray(
            PchipInterpolator(x[indexes][order], y[indexes][order])(x[start : end + 1])
        )
    return np.interp(x[start : end + 1], x[indexes][order], y[indexes][order])


def _groups(flags, grow, max_width):
    indexes = np.flatnonzero(flags)
    if not len(indexes):
        return []
    groups, current = [], [int(indexes[0])]
    for index in indexes[1:]:
        if index <= current[-1] + grow + 1:
            current.append(int(index))
        else:
            groups.append(current)
            current = [int(index)]
    groups.append(current)
    result = []
    for group in groups:
        start, end = max(0, group[0] - grow), min(len(flags) - 1, group[-1] + grow)
        if end - start + 1 <= max_width:
            result.append((start, end))
    return result


def detect_single(x, y, threshold=8.0, window=11, max_width=12, grow=1):
    """Whitaker–Hayes style modified-Z detection of positive, narrow spikes."""
    x, y = _validate_xy(x, y)
    window = max(3, int(window) | 1)
    residual_z = robust_z(y - median_filter(y, size=window, mode="nearest"))
    derivative_z = np.abs(robust_z(np.diff(y)))
    edges = np.zeros(len(y), dtype=bool)
    hit = derivative_z >= threshold * 0.65
    edges[:-1] |= hit
    edges[1:] |= hit
    flags = (residual_z >= threshold) & edges
    margin = min(window // 2, len(y) // 4)
    flags[:margin] = flags[-margin:] = False
    candidates = []
    for start, end in _groups(flags, int(grow), int(max_width)):
        candidates.append(
            Candidate(
                start,
                end,
                float(np.max(residual_z[start : end + 1])),
                "Modified Z-score",
                interpolate_interval(x, y, start, end),
            )
        )
    return candidates


def _onto_grid(curve, target_x):
    x, y = _validate_xy(curve.x, curve.y)
    order = np.argsort(x)
    if target_x.min() < x.min() or target_x.max() > x.max():
        raise ValueError(f"{curve.name}: x range does not cover the selected spectrum.")
    return np.asarray(PchipInterpolator(x[order], y[order])(target_x))


def ensemble_reference(target, selected):
    """Robust median of repeated spectra after iterative affine intensity alignment."""
    x, y = _validate_xy(target.x, target.y)
    if len(selected) < 3:
        raise ValueError("Select at least three repeated spectra, including the active spectrum.")
    aligned = [y]
    for curve in selected:
        if curve.id == target.id:
            continue
        other = _onto_grid(curve, x)
        mask = np.ones(len(y), dtype=bool)
        for _ in range(4):
            if mask.sum() < 10:
                break
            slope, offset = np.polyfit(other[mask], y[mask], 1)
            scaled = slope * other + offset
            z = np.abs(robust_z(y - scaled))
            mask = z < 4.5
        aligned.append(slope * other + offset)
    return np.median(np.vstack(aligned), axis=0)


def detect_ensemble(target, selected, threshold=8.0, window=11, max_width=12, grow=1):
    x, y = _validate_xy(target.x, target.y)
    reference = ensemble_reference(target, selected)
    residual_z = robust_z(y - reference)
    derivative_z = np.abs(robust_z(np.diff(y - reference)))
    edges = np.zeros(len(y), dtype=bool)
    hit = derivative_z >= threshold * 0.5
    edges[:-1] |= hit
    edges[1:] |= hit
    flags = (residual_z >= threshold) & edges
    margin = min((int(window) | 1) // 2, len(y) // 4)
    flags[:margin] = flags[-margin:] = False
    return [
        Candidate(
            a,
            b,
            float(np.max(residual_z[a : b + 1])),
            "Repeated-spectrum median",
            reference[a : b + 1].copy(),
        )
        for a, b in _groups(flags, int(grow), int(max_width))
    ]


def cleaned_values(y, candidates):
    result = np.asarray(y, float).copy()
    for candidate in candidates:
        if candidate.accepted:
            result[candidate.start : candidate.end + 1] = candidate.replacement
    return result


def cosmic_ray_panel(context):
    import pyqtgraph as pg
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QComboBox,
        QDoubleSpinBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )

    services = context.services

    class CosmicRayPanel(QWidget):
        def __init__(self):
            super().__init__()
            self.project_id = context.project.id
            self.curve_id = None
            self.curve_hash = None
            self.base_x = self.base_y = None
            self.candidates = []
            self._updating = False
            layout = QVBoxLayout(self)
            self.title = QLabel("Select a spectrum, then detect or mark cosmic rays.")
            self.title.setWordWrap(True)
            layout.addWidget(self.title)
            self.method = QComboBox()
            self.method.addItems(
                [
                    "Single spectrum — modified Z-score",
                    "Selected repeated spectra — robust median reference",
                ]
            )
            self.threshold = QDoubleSpinBox()
            self.threshold.setRange(3, 30)
            self.threshold.setValue(8)
            self.threshold.setDecimals(1)
            self.window = QSpinBox()
            self.window.setRange(3, 101)
            self.window.setSingleStep(2)
            self.window.setValue(11)
            self.max_width = QSpinBox()
            self.max_width.setRange(1, 100)
            self.max_width.setValue(12)
            self.grow = QSpinBox()
            self.grow.setRange(0, 10)
            self.grow.setValue(1)
            form = QFormLayout()
            form.addRow("Detection method", self.method)
            form.addRow("Sensitivity threshold", self.threshold)
            form.addRow("Median window (points)", self.window)
            form.addRow("Maximum spike width (points)", self.max_width)
            form.addRow("Grow candidate (points)", self.grow)
            layout.addLayout(form)
            row = QHBoxLayout()
            detect = QPushButton("Detect automatically")
            detect.clicked.connect(lambda: self.guard(self.detect))
            self.manual = QPushButton("Indicate manually")
            self.manual.setCheckable(True)
            row.addWidget(detect)
            row.addWidget(self.manual)
            layout.addLayout(row)
            self.plot = pg.PlotWidget()
            self.plot.setMinimumHeight(230)
            self.plot.setLabel("bottom", "x")
            self.plot.setLabel("left", "Intensity")
            self.plot.addLegend()
            self.plot.scene().sigMouseClicked.connect(self.plot_clicked)
            layout.addWidget(self.plot)
            self.table = QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(["Apply", "x range", "Points", "Score", "Source"])
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.table.itemChanged.connect(self.table_changed)
            layout.addWidget(self.table)
            row = QHBoxLayout()
            all_button = QPushButton("Select all")
            none_button = QPushButton("Select none")
            remove = QPushButton("Remove candidate")
            all_button.clicked.connect(lambda: self.set_all(True))
            none_button.clicked.connect(lambda: self.set_all(False))
            remove.clicked.connect(self.remove_selected)
            row.addWidget(all_button)
            row.addWidget(none_button)
            row.addWidget(remove)
            layout.addLayout(row)
            self.accept = QPushButton("Accept modifications")
            self.accept.setObjectName("accept_modifications")
            self.accept.clicked.connect(lambda: self.guard(self.apply))
            layout.addWidget(self.accept)
            self.status = QLabel("No analysis yet. Nothing is changed until you accept.")
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            self.timer = QTimer(self)
            self.timer.setInterval(400)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            self.refresh()

        def guard(self, callback):
            try:
                callback()
            except Exception as exc:
                QMessageBox.warning(self, "Cosmic-ray removal", str(exc))

        def current(self, snapshot):
            return next(
                (c for c in snapshot.project.curves if c.id == snapshot.active_curve_id), None
            )

        def refresh(self):
            try:
                snapshot = services.snapshot()
                curve = self.current(snapshot)
                new_id = curve.id if curve else None
                if snapshot.project.id != self.project_id or new_id != self.curve_id:
                    self.project_id, self.curve_id = snapshot.project.id, new_id
                    self.curve_hash = curve.content_hash if curve else None
                    self.candidates = []
                    if curve is None:
                        self.base_x = self.base_y = None
                        self.title.setText("No spectrum selected")
                    else:
                        self.base_x, self.base_y = curve.x.copy(), curve.y.copy()
                        self.title.setText(curve.name)
                    self.update_table()
                    self.update_plot()
                elif curve is not None and curve.content_hash != self.curve_hash:
                    self.curve_hash = curve.content_hash
                    self.candidates = []
                    self.base_x, self.base_y = curve.x.copy(), curve.y.copy()
                    self.update_table()
                    self.update_plot()
                    self.status.setText("The spectrum changed; run detection again.")
                self.accept.setEnabled(
                    bool(self.candidates and any(c.accepted for c in self.candidates))
                )
            except Exception as exc:
                self.status.setText(str(exc))
                self.accept.setEnabled(False)

        def detect(self):
            snapshot = services.snapshot()
            curve = self.current(snapshot)
            if curve is None:
                raise ValueError("Select a spectrum first.")
            self.base_x, self.base_y, self.curve_id = curve.x.copy(), curve.y.copy(), curve.id
            self.curve_hash = curve.content_hash
            args = (
                self.threshold.value(),
                self.window.value(),
                self.max_width.value(),
                self.grow.value(),
            )
            if self.method.currentIndex() == 0:
                self.candidates = detect_single(curve.x, curve.y, *args)
            else:
                chosen = [c for c in snapshot.project.curves if c.id in snapshot.selected_curve_ids]
                if curve.id not in {c.id for c in chosen}:
                    chosen.append(curve)
                self.candidates = detect_ensemble(curve, chosen, *args)
            self.update_table()
            self.update_plot()
            self.status.setText(
                f"{len(self.candidates)} candidate(s). Review each row and the overlay."
            )

        def plot_clicked(self, event):
            if (
                not self.manual.isChecked()
                or self.base_x is None
                or event.button() != Qt.MouseButton.LeftButton
            ):
                return
            point = self.plot.plotItem.vb.mapSceneToView(event.scenePos())
            index = int(np.argmin(np.abs(self.base_x - point.x())))
            half = self.grow.value()
            start, end = max(0, index - half), min(len(self.base_y) - 1, index + half)
            try:
                replacement = interpolate_interval(self.base_x, self.base_y, start, end)
            except Exception as error:
                QMessageBox.warning(self, "Cosmic-ray removal", str(error))
                return
            self.candidates.append(Candidate(start, end, float("nan"), "Manual", replacement))
            self.candidates.sort(key=lambda c: c.start)
            self.update_table()
            self.update_plot()
            self.status.setText("Manual candidate added; review and accept it if appropriate.")

        def update_table(self):
            self._updating = True
            self.table.setRowCount(len(self.candidates))
            for row, c in enumerate(self.candidates):
                check = QTableWidgetItem()
                check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(
                    Qt.CheckState.Checked if c.accepted else Qt.CheckState.Unchecked
                )
                lo, hi = (
                    sorted((self.base_x[c.start], self.base_x[c.end]))
                    if self.base_x is not None
                    else (0, 0)
                )
                values = [
                    check,
                    QTableWidgetItem(f"{lo:.6g} – {hi:.6g}"),
                    QTableWidgetItem(str(c.end - c.start + 1)),
                    QTableWidgetItem("manual" if not np.isfinite(c.score) else f"{c.score:.1f}"),
                    QTableWidgetItem(c.source),
                ]
                for column, item in enumerate(values):
                    self.table.setItem(row, column, item)
            self.table.resizeColumnsToContents()
            self._updating = False

        def table_changed(self, item):
            if self._updating or item.column() != 0:
                return
            self.candidates[item.row()].accepted = item.checkState() == Qt.CheckState.Checked
            self.update_plot()

        def set_all(self, accepted):
            for c in self.candidates:
                c.accepted = accepted
            self.update_table()
            self.update_plot()

        def remove_selected(self):
            row = self.table.currentRow()
            if row >= 0:
                self.candidates.pop(row)
                self.update_table()
                self.update_plot()

        def update_plot(self):
            self.plot.clear()
            if self.base_x is None:
                return
            self.plot.plot(
                self.base_x, self.base_y, pen=pg.mkPen("#64748b", width=1), name="Original"
            )
            preview = cleaned_values(self.base_y, self.candidates)
            self.plot.plot(
                self.base_x, preview, pen=pg.mkPen("#0ea5a4", width=2), name="Cleaned preview"
            )
            active = [c for c in self.candidates if c.accepted]
            if active:
                centers = [(self.base_x[c.start] + self.base_x[c.end]) / 2 for c in active]
                values = [self.base_y[(c.start + c.end) // 2] for c in active]
                self.plot.plot(
                    centers, values, pen=None, symbol="x", symbolPen="#dc2626", symbolSize=10
                )

        def apply(self):
            snapshot = services.snapshot()
            curve = self.current(snapshot)
            if curve is None or curve.id != self.curve_id:
                raise ValueError("The selected spectrum changed; run detection again.")
            if curve.content_hash != self.curve_hash:
                raise ValueError("The spectrum data changed; run detection again.")
            chosen = [c for c in self.candidates if c.accepted]
            if not chosen:
                raise ValueError("Select at least one correction.")
            result = cleaned_values(self.base_y, chosen)
            metadata = copy.deepcopy(curve.metadata.get(METADATA_KEY, {}))
            history = list(metadata.get("history", []))
            history.append(
                {
                    "method": self.method.currentText(),
                    "threshold": self.threshold.value(),
                    "intervals": [
                        {
                            "x_min": float(min(curve.x[c.start], curve.x[c.end])),
                            "x_max": float(max(curve.x[c.start], curve.x[c.end])),
                            "points": c.end - c.start + 1,
                            "score": None if not np.isfinite(c.score) else c.score,
                            "source": c.source,
                        }
                        for c in chosen
                    ],
                }
            )
            metadata["history"] = history
            if not hasattr(services, "apply_y_replacement"):
                raise ValueError("This plugin requires a newer CurveMole version.")
            services.apply_y_replacement(
                curve.id,
                result,
                description="Accept cosmic-ray corrections",
                metadata_key=METADATA_KEY,
                metadata=metadata,
            )
            self.candidates = []
            self.base_y = result
            updated = services.snapshot()
            updated_curve = self.current(updated)
            self.curve_hash = updated_curve.content_hash if updated_curve else None
            self.update_table()
            self.update_plot()
            self.status.setText(
                f"Accepted {len(chosen)} correction(s). Use Undo to restore the original spectrum."
            )

    return CosmicRayPanel()


def register(api):
    api.add(
        "panels", "review", "Cosmic-ray removal: review and clean", cosmic_ray_panel, auto_show=True
    )
