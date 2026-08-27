from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.registry import default_registry
from curvemole.gui.dialogs import AddComponentDialog, BackgroundComponentsDialog
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace


def make_project() -> tuple[Project, Curve, Component, Component]:
    project = Project("Background UX")
    curve = Curve("curve", [0.0, 1.0, 2.0], [3.0, 4.0, 3.0])
    project.add_curve(curve)
    first = Component.create("constant", initial={"offset": 3.0})
    second = Component.create("gaussian")
    project.model_for(curve.id).add(first)
    project.model_for(curve.id).add(second)
    project.dirty = False
    return project, curve, first, second


def test_add_component_dialog_does_not_label_functions_as_background() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _, _ = make_project()
    dialog = AddComponentDialog(default_registry(), curve)
    labels = [dialog.function.itemText(index) for index in range(dialog.function.count())]
    assert "Constant" in labels
    assert "Cubic spline" in labels
    assert all(" — background" not in label for label in labels)
    dialog.close()
    app.processEvents()


def test_subtract_dialog_first_designates_then_selects_marked_backgrounds() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, first, second = make_project()
    dialog = BackgroundComponentsDialog(project, curve.id, default_registry())
    assert dialog.marking_mode is True
    assert dialog.components.count() == 2
    dialog.components.item(0).setCheckState(Qt.CheckState.Checked)
    assert len(dialog.selected_component_ids()) == 1
    dialog.close()

    first.is_background = True
    marked = BackgroundComponentsDialog(project, curve.id, default_registry())
    assert marked.marking_mode is False
    assert marked.components.count() == 1
    assert marked.selected_component_ids() == [first.id]
    marked.close()
    app.processEvents()


def test_model_panel_can_mark_selected_component_as_background() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, first, _ = make_project()
    window = MainWindow(project)
    window._set_component(first.id)
    window.model_panel.background_toggle.setChecked(True)
    assert first.is_background is True
    assert "Background" in window.model_panel.components.currentItem().text()
    project.dirty = False
    window.close()
    app.processEvents()


def test_spline_points_outside_data_do_not_change_view_range() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _, _ = make_project()
    workspace = PlotWorkspace(default_registry())
    workspace.set_context(project, curve.id, {curve.id}, None)
    workspace.plot.setXRange(-1.0, 3.0, padding=0)
    workspace.plot.setYRange(-2.0, 6.0, padding=0)
    before = workspace.view_box.viewRange()
    workspace.begin_spline_placement("Spline")
    workspace._add_spline_point(10.0, 20.0)
    workspace._add_spline_point(12.0, 18.0)
    after = workspace.view_box.viewRange()
    assert workspace._spline_points == [(10.0, 20.0), (12.0, 18.0)]
    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])
    workspace.cancel_placement()
    workspace.close()
    app.processEvents()
