from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project, Series
from curvemole.core.data import CurveState
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import CopyFitDialog


def test_copy_fit_does_not_mark_source_spectrum_outdated():
    app = QApplication.instance() or QApplication([])
    project = Project()
    source = Curve("Source", [0.0, 1.0], [1.0, 2.0])
    target = Curve("Target", [0.0, 1.0], [1.0, 2.0])
    series = Series("Series", [source, target])
    project.add_series(series)
    project.model_for(source.id).add(Component.create("gaussian"))
    source.state = CurveState.FITTED
    window = CurveMoleMainWindow(project)
    window.show()

    def accept_dialog():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, CopyFitDialog)
        dialog.targets.item(1).setCheckState(Qt.CheckState.Checked)
        dialog.accept()

    QTimer.singleShot(0, accept_dialog)
    window.copy_fit()
    assert source.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()
