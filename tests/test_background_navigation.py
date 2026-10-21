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
    peak_item = window.plot_workspace._component_items[(curve.id, peak.id)]
    _, displayed_peak = peak_item.getOriginalDataset()
    np.testing.assert_allclose(displayed_peak, components[peak.id] + 3.0)

    window.background_subtracted_view_action.setChecked(True)
    app.processEvents()

    _, displayed_data = window.plot_workspace._data_items[curve.id].getOriginalDataset()
    _, displayed_peak = window.plot_workspace._component_items[(curve.id, peak.id)].getOriginalDataset()
    np.testing.assert_allclose(displayed_data, original_y - 3.0)
    np.testing.assert_allclose(displayed_peak, components[peak.id])
    assert not window.plot_workspace._component_items[(curve.id, background.id)].isVisible()
    np.testing.assert_allclose(curve.y, original_y)

    window.background_subtracted_view_action.setChecked(False)
    app.processEvents()
    _, restored_data = window.plot_workspace._data_items[curve.id].getOriginalDataset()
    np.testing.assert_allclose(restored_data, original_y)
    np.testing.assert_allclose(curve.y, original_y)

    project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("mode", [1, 2])
def test_duplicate_component_ids_in_spectra_with_different_lengths(mode: int) -> None:
    """Imported/copy models can reuse component IDs across distinct spectra."""
    import copy

    app = QApplication.instance() or QApplication([])
    project, first, background, peak = _background_fit_project()
    first.name = "same name"
    x = np.linspace(-4., 4., 83)
    second = Curve("same name", x, 8. + np.exp(-x * x))
    project.add_curve(second)
    for source in (background, peak):
        project.model_for(second.id).add(copy.deepcopy(source))
    project.model_for(second.id).component(background.id).parameters["offset"].value = 8.
    project.dirty = False
    window = CurveMoleMainWindow(project)
    workspace = window.plot_workspace
    try:
        workspace.scope_project.setChecked(True)
        workspace.display_mode.setCurrentIndex(mode)
        workspace.y_offset.setValue(11.)
        workspace.x_offset.setValue(2.)
        assert set(workspace._component_items) == {
            (curve.id, component.id)
            for curve in project.curves for component in project.model_for(curve.id).components
        }
        for subtract in (False, True, False):
            window.background_subtracted_view_action.setChecked(subtract)
            workspace.refresh()
            app.processEvents()
            for index, (curve, offset) in enumerate(zip(project.curves, (3., 8.), strict=True)):
                model = project.model_for(curve.id)
                total, components = model.evaluate(
                    curve.x, curve_id=curve.id,
                    values=project.resolved_parameter_values(), components=True,
                )
                shift = index * workspace.y_offset.value() if mode == 2 else 0.
                x_shift = index * workspace.x_offset.value() if mode == 2 else 0.
                peak_item = workspace._component_items[(curve.id, peak.id)]
                x_data, y_data = peak_item.getOriginalDataset()
                np.testing.assert_allclose(x_data, curve.x + x_shift)
                np.testing.assert_allclose(y_data, components[peak.id] + shift + (0. if subtract else offset))
                _, sum_y = workspace._sum_items[curve.id].getOriginalDataset()
                np.testing.assert_allclose(sum_y, total + shift - (offset if subtract else 0.))
                assert workspace._component_items[(curve.id, background.id)].isVisible() != subtract
                assert workspace._component_labels_by_key[(curve.id, background.id)].isVisible() != subtract
                assert workspace._component_labels_by_key[(curve.id, peak.id)].isVisible()

        # The curve identity must also travel with click selection: otherwise a
        # shared component ID targets the active spectrum's parameters.
        assert window.active_curve_id == first.id
        workspace._component_items[(second.id, peak.id)].sigClicked.emit(
            workspace._component_items[(second.id, peak.id)], None
        )
        assert window.active_curve_id == second.id
        assert workspace._selected_component_id == peak.id
        assert window.model_panel.selected_component_refs() == [(second.id, peak.id)]
    finally:
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


@pytest.mark.parametrize("focus", ["tree", "plot"])
def test_arrow_navigation_skips_unchecked_spectra_in_both_directions(focus: str) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("hidden navigation")
    for index in range(5):
        project.add_curve(Curve(f"spectrum {index}", [0.0, 1.0], [index, index + 1.0]))
    project.curves[1].visible = False
    project.curves[3].visible = False
    project.curves[4].visible = False
    project.dirty = False
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    widget = window.curve_tree if focus == "tree" else window.plot_workspace.graphics.viewport()
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()

    for key, expected in ((Qt.Key.Key_Down, 2), (Qt.Key.Key_Down, 2), (Qt.Key.Key_Up, 0)):
        QTest.keyClick(widget, key)
        app.processEvents()
        assert window.active_curve_id == project.curves[expected].id

    # A hidden spectrum selected manually still navigates from its own position.
    window._set_active_curve(project.curves[3].id)
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(widget, Qt.Key.Key_Up)
    app.processEvents()
    assert window.active_curve_id == project.curves[2].id

    # Checking a spectrum immediately puts it back into the navigation sequence.
    parent = window.curve_tree.topLevelItem(0)
    parent.child(1).setCheckState(0, Qt.CheckState.Checked)
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(widget, Qt.Key.Key_Up)
    app.processEvents()
    assert window.active_curve_id == project.curves[1].id

    for index in range(parent.childCount()):
        parent.child(index).setCheckState(0, Qt.CheckState.Unchecked)
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()
    QTest.keyClick(widget, Qt.Key.Key_Down)
    app.processEvents()
    assert window.active_curve_id == project.curves[1].id
    project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("dark", [False, True])
def test_unchecked_spectrum_names_are_muted_and_restore_on_check(dark: bool) -> None:
    from PySide6.QtGui import QColor, QPalette

    from curvemole.gui.main_window import CurveTree

    app = QApplication.instance() or QApplication([])
    project = Project("muted names")
    curve = Curve("spectrum", [0.0, 1.0], [1.0, 2.0])
    curve.visible = False
    project.add_curve(curve)
    tree = CurveTree()
    palette = tree.palette()
    palette.setColor(QPalette.ColorRole.Text, QColor("#eeeeee" if dark else "#111111"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#111111" if dark else "#eeeeee"))
    tree.setPalette(palette)
    tree.populate(project, curve.id)
    item = tree.topLevelItem(0).child(0)
    normal = palette.color(QPalette.ColorRole.Text)
    muted = item.foreground(1).color()
    assert muted != normal
    assert (muted.lightness() < normal.lightness()) if dark else (muted.lightness() > normal.lightness())
    item.setCheckState(0, Qt.CheckState.Checked)
    assert item.foreground(1).color() == normal
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert item.foreground(1).color() == muted
    palette.setColor(QPalette.ColorRole.Base, QColor("#555555"))
    tree.setPalette(palette)
    assert item.foreground(1).color() != muted
    assert item.flags() & Qt.ItemFlag.ItemIsEnabled
    tree.close()
    app.processEvents()
