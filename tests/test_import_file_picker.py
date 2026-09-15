import time

import numpy as np
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from curvemole.gui.import_file_picker import ImportFileDialog


def wait_for(app, condition):
    deadline = time.monotonic() + 8
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert condition()


def test_file_highlight_and_column_preview_before_acceptance(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "sample.csv"
    x = np.linspace(0, 10, 6000)
    y = np.sin(x)
    y[2300] = 12
    np.savetxt(path, np.column_stack([x, y, x**2]), delimiter=",", header="x,y,monitor", comments="")
    dialog = ImportFileDialog()
    assert dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
    assert dialog.fileMode() == QFileDialog.FileMode.ExistingFiles
    dialog.currentChanged.emit(str(path))
    wait_for(app, lambda: dialog._columns is not None)
    assert dialog.result() != QFileDialog.DialogCode.Accepted
    assert (dialog.x_column.currentIndex(), dialog.y_column.currentIndex()) == (0, 1)
    item = dialog.graph.listDataItems()[0]
    assert item.opts["autoDownsample"]
    assert dialog.graph.viewRange()[1][1] >= 12
    dialog.y_column.setCurrentIndex(2)
    np.testing.assert_allclose(dialog.graph.listDataItems()[0].yData, x**2)
    assert dialog.column_choices[str(path.resolve())] == (0, 2)
    dialog.reject()
    app.processEvents()


def test_stale_read_and_invalid_file_do_not_plot_previous_spectrum(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    bad = tmp_path / "binary.dat"
    first.write_text("x y\n1 2\n2 3\n")
    second.write_text("x y\n1 20\n2 30\n")
    bad.write_bytes(b"\0not a spectrum")
    dialog = ImportFileDialog()
    dialog.preview_path(str(first))
    dialog._timer.stop()
    dialog._read()
    dialog.preview_path(str(second))
    wait_for(app, lambda: dialog._columns is not None)
    np.testing.assert_allclose(dialog.graph.listDataItems()[0].yData, [20, 30])
    dialog.preview_path(str(bad))
    wait_for(app, lambda: "unavailable" in dialog.preview_label.text())
    assert not dialog.graph.listDataItems()
    dialog.preview_path(str(first))
    dialog._timer.stop()
    dialog._read()
    dialog.reject()
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    assert not dialog._timer.isActive()
