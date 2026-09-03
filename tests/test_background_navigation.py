from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.gui.app import CurveMoleMainWindow


def _background_fit_project(
    name: str = "background display",
) -> tuple[Project, Curve, Component, Component]:
    x = np.linspace(-4.0, 4.0, 161)
    sigma = 0.7
    peak_y = 4.0 * np.exp(-0.5 * ((x - 0.5) / sigma) ** 2) / (
        sigma * np.sqrt(2.0 * np.pi)
    )
    curve = Curve("spectrum", x, 3.0 + peak_y)
    project = Project(name)
    project.add_curve(curve)
    background = Component.create("constant", initial={"offset": 3.0})
    background.is_background = True
    peak = Component.create(
        "gaussian",
        initial={"area": 4.0, "center": 0.5, "sigma": sigma},
    )
    model = project.model_for(curve.id)
    model.add(background)
    model.add(peak)
    project.dirty = False
    return project, curve, background, peak


def test_fit_components_follow_background_and_visual_subtraction_is_non_destructive() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, background, peak = _background_fit_project()
    original_y = curve.y.copy()
    window = CurveMoleMainWindow(project)
    app.processEvents()

    model = project.model_for(curve.id)
    _, components = model.evaluate(
        curve.x,
        curve_id=curve.id,
        values=project.resolved_parameter_values(),
        registry=window.registry,
        components=True,
    )
    peak_item = window.plot_workspace._component_items[peak.id]
    _, displayed_peak = peak_item.getOriginalDataset()
    np.testing.assert_allclose(displayed_peak, components[peak.id] + 3.0)

    window.background_subtracted_view_action.setChecked(True)
    app.processEvents()

    _, displayed_data = window.plot_workspace._data_items[curve.id].getOriginalDataset()
    _, displayed_peak = window.plot_workspace._component_items[peak.id].getOriginalDataset()
    np.testing.assert_allclose(displayed_data, original_y - 3.0)
    np.testing.assert_allclose(displayed_peak, components[peak.id])
    assert not window.plot_workspace._component_items[background.id].isVisible()
    np.testing.assert_allclose(curve.y, original_y)

    window.background_subtracted_view_action.setChecked(False)
    app.processEvents()
    _, restored_data = window.plot_workspace._data_items[curve.id].getOriginalDataset()
    np.testing.assert_allclose(restored_data, original_y)
    np.testing.assert_allclose(curve.y, original_y)

    project.dirty = False
    window.close()
    app.processEvents()


def test_subtract_all_backgrounds_changes_every_eligible_curve_and_is_undoable() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("global background")
    originals: dict[str, np.ndarray] = {}
    backgrounds: list[Component] = []

    for index, offset in enumerate((2.0, 5.0)):
        x = np.linspace(0.0, 4.0, 21)
        y = offset + np.linspace(1.0, 2.0, len(x))
        curve = Curve(f"spectrum {index}", x, y)
        project.add_curve(curve)
        component = Component.create("constant", initial={"offset": offset})
        component.is_background = True
        project.model_for(curve.id).add(component)
        originals[curve.id] = curve.y.copy()
        backgrounds.append(component)

    project.dirty = False
    window = CurveMoleMainWindow(project)
    window.subtract_all_backgrounds()
    app.processEvents()

    for curve, offset, component in zip(project.curves, (2.0, 5.0), backgrounds, strict=True):
        np.testing.assert_allclose(curve.y, originals[curve.id] - offset)
        assert component.is_background is True
        assert component.enabled is False

    window.undo_stack.undo()
    app.processEvents()
    for curve, component in zip(project.curves, backgrounds, strict=True):
        np.testing.assert_allclose(curve.y, originals[curve.id])
        assert component.is_background is True
        assert component.enabled is True

    project.dirty = False
    window.close()
    app.processEvents()


def test_plot_focus_arrow_keys_step_through_spectra_like_the_curve_tree() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("keyboard navigation")
    for index in range(3):
        project.add_curve(Curve(f"spectrum {index}", [0.0, 1.0], [index, index + 1.0]))
    project.dirty = False
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()

    assert window.active_curve_id == project.curves[0].id
    viewport = window.plot_workspace.graphics.viewport()
    viewport.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()

    QTest.keyClick(viewport, Qt.Key.Key_Down)
    app.processEvents()
    assert window.active_curve_id == project.curves[1].id

    QTest.keyClick(viewport, Qt.Key.Key_Down)
    app.processEvents()
    assert window.active_curve_id == project.curves[2].id

    QTest.keyClick(viewport, Qt.Key.Key_Up)
    app.processEvents()
    assert window.active_curve_id == project.curves[1].id

    project.dirty = False
    window.close()
    app.processEvents()
