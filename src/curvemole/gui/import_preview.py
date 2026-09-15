"""Full-spectrum column-mapping preview using the shared adaptive renderer."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from curvemole.core.importers import ImportPreview
from curvemole.gui.rendering import _optimise_plot_data_item


class SpectrumImportPreview(QWidget):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.cache = None
        self.cache_key = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("Spectrum preview")
        layout.addWidget(self.label)
        self.graph = pg.PlotWidget()
        self.graph.setMinimumHeight(150)
        self.graph.setMaximumHeight(220)
        self.graph.setBackground(self.palette().color(QPalette.ColorRole.Base))
        foreground = self.palette().color(QPalette.ColorRole.Text)
        for name in ("left", "bottom"):
            self.graph.getAxis(name).setPen(foreground)
            self.graph.getAxis(name).setTextPen(foreground)
        self.graph.showGrid(x=True, y=True, alpha=0.15)
        self.graph.addLegend(offset=(8, 8), labelTextColor=foreground.name())
        layout.addWidget(self.graph)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)
        dialog.x_column.currentIndexChanged.connect(self.schedule)
        dialog.y_columns.itemChanged.connect(self.schedule)
        for combo in (dialog.sigma_x, dialog.uncertainty_column, dialog.uncertainty_kind):
            combo.currentIndexChanged.connect(self.schedule)
        self.schedule()

    def schedule(self, *_):
        self.timer.start()

    def refresh(self):
        self.graph.clear()
        self.label.setToolTip("")
        dialog = self.dialog
        try:
            mapping = dialog.mapping()
            if not mapping.y:
                self.label.setText("Spectrum preview — select at least one Y column")
                return
            config = dialog.config()
            info = dialog.path.stat()
            key = (info.st_mtime_ns, info.st_size, repr(config))
            if key != self.cache_key:
                cache = ImportPreview(dialog.path, config)
                self.cache, self.cache_key = cache, key
            curves = self.cache.curves(mapping)
            colours = (["#66B5FF", "#FFAD5C", "#56CCA4", "#E49CD8", "#FFD166"]
                       if self.palette().color(QPalette.ColorRole.Base).lightness() < 128
                       else ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00"])
            all_x, all_y = [], []
            for index, curve in enumerate(curves):
                valid = np.isfinite(curve.x) & np.isfinite(curve.y)
                x, y = curve.x[valid], curve.y[valid]
                if not len(x):
                    continue
                item = self.graph.plot(x, y, name=curve.name, pen=pg.mkPen(colours[index % len(colours)]))
                _optimise_plot_data_item(item, adaptive=True)
                all_x.extend((float(x.min()), float(x.max())))
                all_y.extend((float(y.min()), float(y.max())))
            if all_x:
                # Range comes from full arrays, never the clipped/downsampled line.
                self.graph.setRange(xRange=(min(all_x), max(all_x)),
                                    yRange=(min(all_y), max(all_y)), padding=0.04)
                self.label.setText(f"Spectrum preview — {dialog.path.name}")
            else:
                self.label.setText("Spectrum preview — no finite X/Y pairs")
            self.graph.setLabel("bottom", str(mapping.x))
            self.graph.setLabel("left", ", ".join(str(y) for y in mapping.y))
        except Exception as exc:
            self.label.setText("Spectrum preview unavailable")
            self.label.setToolTip(str(exc))
