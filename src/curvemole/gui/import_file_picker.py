"""Multi-file chooser with an asynchronous preview before files are accepted."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from curvemole.core.importers import ImportPreview, _numeric, detect_config
from curvemole.gui.rendering import _optimise_plot_data_item


class _Signals(QObject):
    ready = Signal(int, str, object, str)


class _ReadPreview(QRunnable):
    def __init__(self, generation, path):
        super().__init__()
        self.generation, self.path = generation, path
        self.signals = _Signals()

    def run(self):
        try:
            with open(self.path, "rb") as source:
                if b"\0" in source.read(4096):
                    raise ValueError("This file is not a text table.")
            cache = ImportPreview(self.path, detect_config(self.path))
            # Convert once off the GUI thread; changing axes only redraws arrays.
            columns = [(_numeric(cache.frame[name], cache.config.decimal), str(name))
                       for name in cache.frame.columns]
            self.signals.ready.emit(self.generation, self.path, columns, "")
        except Exception as exc:
            self.signals.ready.emit(self.generation, self.path, None, str(exc))


class ImportFileDialog(QFileDialog):
    def __init__(self, parent=None):
        super().__init__(parent, self.tr("Import one-dimensional curves"))
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.ExistingFiles)
        self.setNameFilters([self.tr("All readable data (*)"),
                             self.tr("Common XY/text data (*.txt *.dat *.csv *.tsv *.xy)")])
        self.resize(960, 760)
        self.column_choices = {}
        self._generation = 0
        self._path = ""
        self._columns = None
        self._workers = {}
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        self.preview_label = QLabel(self.tr("Select a file to preview its spectrum"))
        layout.addWidget(self.preview_label)
        row = QHBoxLayout()
        self.x_column, self.y_column = QComboBox(), QComboBox()
        for label, combo in (("X", self.x_column), ("Y", self.y_column)):
            row.addWidget(QLabel(label))
            row.addWidget(combo, 1)
            combo.currentIndexChanged.connect(self._plot)
        layout.addLayout(row)
        self.graph = pg.PlotWidget()
        self.graph.setMinimumHeight(150)
        self.graph.setMaximumHeight(220)
        self.graph.setBackground(self.palette().color(QPalette.ColorRole.Base))
        foreground = self.palette().color(QPalette.ColorRole.Text)
        for name in ("left", "bottom"):
            self.graph.getAxis(name).setPen(foreground)
            self.graph.getAxis(name).setTextPen(foreground)
        self.graph.showGrid(x=True, y=True, alpha=0.15)
        layout.addWidget(self.graph)
        grid = self.layout()
        grid.addWidget(panel, grid.rowCount(), 0, 1, grid.columnCount())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._read)
        self.currentChanged.connect(self.preview_path)
        self.finished.connect(self._finish_preview)

    @Slot(str)
    def preview_path(self, path):
        self._generation += 1
        self._path = str(Path(path).resolve())
        self._columns = None
        self.graph.clear()
        self.x_column.clear()
        self.y_column.clear()
        self.preview_label.setToolTip("")
        self._timer.stop()
        if Path(path).is_file():
            self.preview_label.setText(self.tr("Loading preview…"))
            self._timer.start()
        else:
            self.preview_label.setText(self.tr("Select a file to preview its spectrum"))

    def _read(self):
        # At most one read in flight; keep only the most recent pending file.
        if self._workers:
            return
        worker = _ReadPreview(self._generation, self._path)
        self._workers[self._generation] = worker
        worker.signals.ready.connect(self._loaded)
        QThreadPool.globalInstance().start(worker)

    @Slot(int, str, object, str)
    def _loaded(self, generation, path, columns, error):
        self._workers.pop(generation, None)
        if generation != self._generation:
            if self._path and Path(self._path).is_file():
                self._timer.start()
            return
        if error:
            self.preview_label.setText(self.tr("Preview unavailable — adjust parsing after opening"))
            self.preview_label.setToolTip(error)
            return
        self._columns = columns
        selected = self.column_choices.get(path, (0, 1))
        for combo, index in ((self.x_column, selected[0]), (self.y_column, selected[1])):
            combo.blockSignals(True)
            combo.clear()
            for number, (_, name) in enumerate(columns, 1):
                combo.addItem(f"c{number} — {name}")
            combo.setCurrentIndex(min(index, len(columns) - 1))
            combo.blockSignals(False)
        self._plot()

    def _plot(self, *_):
        self.graph.clear()
        if self._columns is None or min(self.x_column.currentIndex(), self.y_column.currentIndex()) < 0:
            return
        xi, yi = self.x_column.currentIndex(), self.y_column.currentIndex()
        self.column_choices[self._path] = (xi, yi)
        x, x_name = self._columns[xi]
        y, y_name = self._columns[yi]
        valid = np.isfinite(x) & np.isfinite(y)
        x, y = x[valid], y[valid]
        if not len(x):
            self.preview_label.setText(self.tr("No finite X/Y pairs in these columns"))
            return
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        item = self.graph.plot(x, y, pen=pg.mkPen("#66B5FF" if dark else "#0072B2"))
        _optimise_plot_data_item(item, adaptive=True)
        self.graph.setRange(xRange=(float(x.min()), float(x.max())),
                            yRange=(float(y.min()), float(y.max())), padding=0.04)
        self.graph.setLabel("bottom", x_name)
        self.graph.setLabel("left", y_name)
        self.preview_label.setText(self.tr("Spectrum preview — ") + Path(self._path).name)

    def _finish_preview(self, *_):
        self._generation += 1
        self._path = ""
        self._timer.stop()


def choose_import_files(parent):
    dialog = ImportFileDialog(parent)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return [], {}
    return dialog.selectedFiles(), dict(dialog.column_choices)
