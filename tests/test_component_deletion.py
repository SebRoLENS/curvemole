from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.errors import DataValidationError
from curvemole.core.models import Model
from curvemole.gui.app import CurveMoleMainWindow


def example(operator="multiply"):
    project = Project()
    x = np.linspace(-5., 5., 101)
    curve = Curve("Spectrum", x, np.exp(-x * x))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    base = Component.create("gaussian")
    factor = Component.create("constant", initial={"offset": 2.})
    factor.operator = operator
    other = Component.create("gaussian", initial={"center": 2.})
    for component in (base, factor, other):
        model.add(component)
    # Presentation order must not decide which function starts evaluation.
    model.display_order = [other.id, base.id, factor.id]
    return project, curve, base, factor, other


def close(window, app):
    window.project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("operator", ["multiply", "divide", "convolve"])
def test_delete_initial_add_keeps_remaining_model_visible_and_undo_restores_composition(monkeypatch, operator):
    app = QApplication.instance() or QApplication([])
    project, curve, base, factor, other = example(operator)
    before = project.model_for(curve.id).to_dict()
    original_y = curve.y.copy()
    original_fit = project.model_for(curve.id).evaluate(curve.x, curve_id=curve.id)
    broken = Model.from_dict(before)
    broken.remove(base.id)
    with pytest.raises(DataValidationError, match="First enabled component"):
        broken.evaluate(curve.x, curve_id=curve.id)

    window = CurveMoleMainWindow(project)
    before = project.model_for(curve.id).to_dict()
    questions = []

    def accept(*args):
        questions.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", accept)
    try:
        window.delete_component(base.id)
        model = project.model_for(curve.id)
        assert [component.id for component in model.components] == [factor.id, other.id]
        assert model.component(factor.id).operator == "add"
        assert "using Add" in questions[0]
        assert set(window.plot_workspace._component_items) == {factor.id, other.id}
        assert set(window.plot_workspace._data_items) == {curve.id}
        remaining_fit = model.evaluate(curve.x, curve_id=curve.id)
        assert np.all(np.isfinite(remaining_fit))
        np.testing.assert_allclose(remaining_fit, 2. + Model(components=[other]).evaluate(curve.x))
        np.testing.assert_array_equal(curve.y, original_y)
        window.undo_stack.undo()
        assert project.model_for(curve.id).to_dict() == before
        np.testing.assert_allclose(project.model_for(curve.id).evaluate(curve.x, curve_id=curve.id), original_fit)
        window.undo_stack.redo()
        np.testing.assert_allclose(project.model_for(curve.id).evaluate(curve.x, curve_id=curve.id), remaining_fit)
    finally:
        close(window, app)


def test_delete_later_add_preserves_multiplication(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project, curve, base, factor, other = example()
    window = CurveMoleMainWindow(project)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    try:
        window.delete_component(other.id)
        model = project.model_for(curve.id)
        assert model.component(factor.id).operator == "multiply"
        np.testing.assert_allclose(model.evaluate(curve.x, curve_id=curve.id),
                                   2. * Model(components=[base]).evaluate(curve.x))
        assert set(window.plot_workspace._component_items) == {base.id, factor.id}
    finally:
        close(window, app)


def test_deletion_with_dependent_link_is_rejected_without_changing_project_or_plot(monkeypatch):
    app = QApplication.instance() or QApplication([])
    project, curve, base, _, other = example()
    other.parameters["center"].link = f"${{{curve.id}.{base.id}.center}}"
    before = project.model_for(curve.id).to_dict()
    window = CurveMoleMainWindow(project)
    before = project.model_for(curve.id).to_dict()
    errors = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(window, "_show_error", lambda title, error: errors.append(str(error)))
    try:
        window.delete_component(base.id)
        assert project.model_for(curve.id).to_dict() == before
        assert window.undo_stack.count() == 0
        assert "Remove the following links or constraints first" in errors[0]
        assert set(window.plot_workspace._component_items) == {component.id for component in project.model_for(curve.id).components}
    finally:
        close(window, app)


def test_invalid_link_does_not_hide_data_or_healthy_cross_spectrum_models():
    app = QApplication.instance() or QApplication([])
    project, curve, _, factor, other = example()
    healthy = Curve("Healthy linked spectrum", curve.x.copy(), curve.y.copy())
    project.add_curve(healthy)
    linked = Component.create("gaussian")
    linked.parameters["area"].link = f"${{{curve.id}.{factor.id}.offset}}"
    project.model_for(healthy.id).add(linked)
    broken = Curve("Broken spectrum", curve.x.copy(), curve.y.copy())
    project.add_curve(broken)
    invalid = Component.create("gaussian")
    invalid.parameters["center"].link = "${missing.function.center}"
    project.model_for(broken.id).add(invalid)
    window = CurveMoleMainWindow(project)
    try:
        workspace = window.plot_workspace
        workspace.display_mode.setCurrentIndex(1)
        workspace.scope_project.setChecked(True)
        workspace.refresh()
        assert set(workspace._data_items) == {curve.id, healthy.id, broken.id}
        assert linked.id in workspace._component_items
        assert other.id in workspace._component_items
        assert invalid.id not in workspace._component_items
        assert "missing.function.center" in workspace.plot.toolTip()
    finally:
        close(window, app)
