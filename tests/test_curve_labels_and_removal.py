from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.fitting import FitMode, FitResult, FitSettings
from curvemole.gui.main_window import MainWindow


def _project_with_curve() -> tuple[Project, Curve]:
    project = Project("labels")
    curve = Curve("curve", np.linspace(-5.0, 5.0, 101), np.exp(-np.linspace(-5.0, 5.0, 101) ** 2))
    project.add_curve(curve)
    project.dirty = False
    return project, curve


def test_components_get_systematic_names_and_labels_are_on_by_default() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve = _project_with_curve()
    model = project.model_for(curve.id)
    model.add(Component.create("voigt"))
    model.add(Component.create("voigt"))
    window = MainWindow(project)
    assert [component.name for component in model.components] == ["Voigt1", "Voigt2"]
    window.plot_workspace.refresh()
    assert window.plot_workspace.component_labels_action.isChecked()
    assert [label.textItem.toPlainText() for label in window.plot_workspace._component_labels] == ["Voigt1", "Voigt2"]
    window.plot_workspace.component_labels_action.setChecked(False)
    assert window.plot_workspace._component_labels == []
    project.dirty = False
    window.close()
    app.processEvents()


def test_new_and_duplicated_components_continue_numbering() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve = _project_with_curve()
    model = project.model_for(curve.id)
    first = Component.create("voigt")
    model.add(first)
    window = MainWindow(project)
    second = Component.create("voigt")
    window._commit_component(second, curve.id)
    assert [item.name for item in project.model_for(curve.id).components] == ["Voigt1", "Voigt2"]
    window.duplicate_component(second.id)
    assert [item.name for item in project.model_for(curve.id).components] == ["Voigt1", "Voigt2", "Voigt3"]
    project.dirty = False
    window.close()
    app.processEvents()


def test_remove_selected_curve_is_undoable(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("remove")
    first = Curve("first", [0.0, 1.0], [0.0, 1.0])
    second = Curve("second", [0.0, 1.0], [1.0, 0.0])
    project.add_curve(first)
    project.add_curve(second)
    project.dirty = False
    window = MainWindow(project)
    window.curve_tree.select_all_curves()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.remove_selected_curves()
    assert project.curves == []
    window.undo_stack.undo()
    assert [curve.id for curve in project.curves] == [first.id, second.id]
    window.undo_stack.redo()
    assert project.curves == []
    project.dirty = False
    window.close()
    app.processEvents()


def test_fit_completion_refreshes_and_auto_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project, curve = _project_with_curve()
    window = MainWindow(project)
    calls = {"range": 0}
    monkeypatch.setattr(window.plot_workspace, "auto_range", lambda: calls.__setitem__("range", calls["range"] + 1))
    result = FitResult(
        success=True,
        mode=FitMode.INDEPENDENT,
        message="ok",
        status=1,
        evaluations=1,
        parameters={},
        curve_outputs={},
        statistics={},
        warnings=[],
        settings=FitSettings(),
        free_parameter_paths=[],
    )
    window._fit_finished(result)
    assert calls["range"] == 1
    project.dirty = False
    window.close()
    app.processEvents()
