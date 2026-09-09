from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project, Series
from curvemole.core.fitting import FitMode, FitSettings
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import CopyFitDialog, FitPlanDialog


def example():
    project = Project()
    for name in ("Pressure scan", "Reference"):
        project.add_series(Series(name, [Curve(f"{name} {i}", [0., 1.], [1., 2.]) for i in range(3)]))
    project.add_component(project.curves[0].id, Component.create("gaussian"))
    return project


def test_scopes_exclude_hidden_targets_and_keep_weights():
    app = QApplication.instance() or QApplication([])
    project = example()
    ids = [curve.id for curve in project.curves]
    dialog = CopyFitDialog(project, ids[0])
    dialog.select_all_targets_button.click()
    assert dialog.choices()[0] == ids[1:3]
    dialog.all_series.click()
    dialog.select_all_targets_button.click()
    assert dialog.choices()[0] == ids[1:]
    dialog.active_series.click()
    assert dialog.choices()[0] == ids[1:3]
    fit = FitPlanDialog(project, {ids[0]}, FitSettings())
    fit.mode.setCurrentIndex(fit.mode.findData(FitMode.SEQUENTIAL))
    assert fit.plan().curve_ids == ids[:3]
    fit.all_series.click()
    fit.select_all_curves_button.click()
    assert fit.plan().curve_ids == ids
    for row in fit._series_rows:
        if fit.curves.item(row, 0).data(Qt.ItemDataRole.UserRole) == ids[1]:
            fit.curves.item(row, 2).setText("2.5")
    fit.active_series.click()
    assert fit.plan().curve_ids == ids[:3]
    assert fit.plan().spectrum_weights[ids[1]] == 2.5
    assert {fit.sequential_source.itemData(i) for i in range(fit.sequential_source.count())} == {None, *ids[:3]}
    dialog.close()
    fit.close()
    app.processEvents()


def test_copy_next_button_preselects_successor_and_preserves_undo():
    app = QApplication.instance() or QApplication([])
    project = example()
    window = CurveMoleMainWindow(project)
    source, target = project.curves[:2]
    before = project.model_for(target.id).to_dict()
    seen = []

    def accept():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, CopyFitDialog)
        seen.extend(dialog.choices()[0])
        dialog.accept()

    QTimer.singleShot(0, accept)
    window.model_panel.copy_fit_next_button.click()
    assert seen == [target.id]
    assert project.model_for(target.id).components[0].function_id == "gaussian"
    window.undo_stack.undo()
    assert project.model_for(target.id).to_dict() == before
    window._set_active_curve(project.curves[2].id)
    assert not window.model_panel.copy_fit_next_button.isEnabled()
    project.dirty = False
    window.close()
    app.processEvents()
