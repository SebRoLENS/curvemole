from __future__ import annotations

import colorsys

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QMessageBox

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState, Series
from curvemole.core.fitting import FitMode, FitPlan, FitSettings, Fitter
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.colours import (
    MODEL_SUM_COLOUR,
    SERIES_PALETTES,
    series_palette_colours,
    spectrum_colour_allowed,
)
from curvemole.gui.main_window import PALETTE, MainWindow


def _gaussian_project() -> tuple[Project, Curve, Component]:
    x = np.linspace(-5.0, 5.0, 301)
    sigma = 0.75
    y = 2.4 * np.exp(-0.5 * ((x - 0.65) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
    curve = Curve("spectrum", x, y)
    project = Project("fit display")
    project.add_curve(curve)
    component = Component.create(
        "gaussian", initial={"area": 1.0, "center": -1.0, "sigma": 1.5}
    )
    project.model_for(curve.id).add(component)
    project.dirty = False
    return project, curve, component


def test_fit_finished_commits_returned_estimates_to_displayed_model() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, component = _gaussian_project()
    window = MainWindow(project)
    model = project.model_for(curve.id)
    result = Fitter(window.registry).fit_single(
        curve, model, FitSettings(max_nfev=4000)
    )
    assert result.success

    # Simulate the GUI holding the pre-fit values when the worker result arrives.
    component.parameters["area"].value = 1.0
    component.parameters["center"].value = -1.0
    component.parameters["sigma"].value = 1.5
    window._fit_finished(result)

    for path, estimate in result.parameters.items():
        assert project.parameter_map()[path].value == pytest.approx(estimate.value)
    rendered = model.evaluate(
        curve.x,
        curve_id=curve.id,
        values=project.resolved_parameter_values(),
        registry=window.registry,
    )
    output = result.curve_outputs[curve.id]
    np.testing.assert_allclose(rendered[output.indices], output.fitted, rtol=1e-9, atol=1e-11)
    assert curve.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()


def test_failed_multicore_refit_updates_the_spectrum_state() -> None:
    app = QApplication.instance() or QApplication([])
    project, good, _ = _gaussian_project()
    bad = Curve("invalid spectrum", good.x, good.y)
    project.add_curve(bad)
    bad.state = CurveState.FITTED
    plan = FitPlan([good.id, bad.id], FitMode.INDEPENDENT, FitSettings(workers=2))
    window = MainWindow(project)
    window._running_fit_plan = plan
    result = Fitter().fit(plan, project.curves, project.models)
    window._fit_finished(result)

    assert good.state == CurveState.FITTED
    assert bad.state == CurveState.FAILED
    assert good.id in project.results["fit_by_curve"]
    assert bad.id not in project.results["fit_by_curve"]
    states = {window.curve_tree.topLevelItem(0).child(index).text(2)
              for index in range(window.curve_tree.topLevelItem(0).childCount())}
    assert states == {CurveState.FITTED.value, CurveState.FAILED.value}
    project.dirty = False
    window.close()
    app.processEvents()


def test_unexpected_fit_task_error_marks_attempted_spectra_failed(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _ = _gaussian_project()
    curve.state = CurveState.FITTED
    window = MainWindow(project)
    window._running_fit_plan = FitPlan([curve.id])
    window._fit_task_active = True
    monkeypatch.setattr(window, "_show_error", lambda *_: None)

    window._task_failed("Unexpected worker error", "traceback")

    assert curve.state == CurveState.FAILED
    assert window.curve_tree.topLevelItem(0).child(0).text(2) == CurveState.FAILED.value
    project.dirty = False
    window.close()
    app.processEvents()


def test_fit_refresh_preserves_current_plot_view() -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _ = _gaussian_project()
    window = CurveMoleMainWindow(project)
    app.processEvents()

    window.plot_workspace.view_box.setRange(
        xRange=[-0.4, 1.4],
        yRange=[0.15, 1.15],
        padding=0,
    )
    before = window.plot_workspace.view_box.viewRange()

    model = project.model_for(curve.id)
    result = Fitter(window.registry).fit_single(
        curve, model, FitSettings(max_nfev=4000)
    )
    assert result.success
    window._fit_finished(result)
    app.processEvents()
    after = window.plot_workspace.view_box.viewRange()

    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])
    project.dirty = False
    window.close()
    app.processEvents()


def test_regular_refresh_preserves_current_plot_view() -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _ = _gaussian_project()
    window = CurveMoleMainWindow(project)
    app.processEvents()

    window.plot_workspace.view_box.setRange(
        xRange=[-1.2, 0.8],
        yRange=[0.05, 0.9],
        padding=0,
    )
    before = window.plot_workspace.view_box.viewRange()
    window.refresh_all()
    app.processEvents()
    after = window.plot_workspace.view_box.viewRange()

    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])
    project.dirty = False
    window.close()
    app.processEvents()


def test_builtin_spectrum_palettes_are_distinct_from_the_default_model_sum() -> None:
    assert MODEL_SUM_COLOUR.upper() == "#D62728"
    assert not spectrum_colour_allowed(MODEL_SUM_COLOUR)
    assert all(spectrum_colour_allowed(colour) for colours in SERIES_PALETTES.values() for colour in colours)
    assert all(colour.upper() != MODEL_SUM_COLOUR.upper() for colour in PALETTE)


def test_automatic_palettes_have_dark_background_contrast_and_red_accents() -> None:
    assert {"Neon", "Sunset", "Jewel"} <= SERIES_PALETTES.keys()
    for name, palette in SERIES_PALETTES.items():
        assert series_palette_colours(name, MODEL_SUM_COLOUR) == palette
        has_red = False
        for colour in palette:
            rgb = [channel / 255 for channel in bytes.fromhex(colour[1:])]
            hue, saturation, _ = colorsys.rgb_to_hsv(*rgb)
            has_red |= saturation >= 0.25 and min(hue, 1 - hue) <= 15 / 360
            linear_rgb = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in rgb
            ]
            luminance = sum(value * weight for value, weight in zip(linear_rgb, (0.2126, 0.7152, 0.0722), strict=True))
            assert (luminance + 0.05) / 0.05 >= 4.5, (name, colour)
        assert has_red == (name not in {"Colourblind", "Grayscale"})


@pytest.mark.parametrize("selected_only", [False, True])
def test_automatic_palette_skips_a_colour_near_a_custom_fit(selected_only):
    app = QApplication.instance() or QApplication([])
    project = Project("Automatic colour")
    series = Series("Spectra")
    for index in range(3):
        series.add(Curve(str(index), [0.0, 1.0], [1.0, 2.0]))
    project.add_series(series)
    window = MainWindow(project)
    appearance = window.plot_workspace.plot_appearance()
    fit_colour = "#E96578"
    appearance["model_sum_colour"] = fit_colour
    window.plot_workspace.set_plot_appearance(appearance)
    before = [curve.colour for curve in series.curves]
    try:
        close_red = "#FF6F7E"
        assert spectrum_colour_allowed(close_red, fit_colour)
        palette = series_palette_colours("Sunset", fit_colour)
        assert close_red not in palette
        if selected_only:
            window.apply_selected_palette([curve.id for curve in series.curves], "Sunset")
        else:
            window.apply_series_palette(series.id, "Sunset")
        assert [curve.colour for curve in series.curves] == list(palette[:3])
        window.undo_stack.undo()
        assert [curve.colour for curve in series.curves] == before
    finally:
        project.dirty = False
        window.close()
        app.processEvents()


@pytest.mark.parametrize("colour", ["#FF0000", "#8B0000", "#F08080", "#B22222"])
def test_red_shades_distinct_from_the_fit_are_available(colour):
    assert spectrum_colour_allowed(colour)


def test_series_palette_changes_colours_without_invalidating_fits() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("palette")
    series = Series("series")
    for index in range(4):
        curve = Curve(f"curve {index}", [0.0, 1.0], [float(index), float(index + 1)])
        curve.state = CurveState.FITTED
        series.add(curve)
    project.add_series(series)
    project.dirty = False
    window = MainWindow(project)
    window.apply_series_palette(series.id, "Ocean")
    expected = list(SERIES_PALETTES["Ocean"][:4])
    assert [curve.colour for curve in series.curves] == expected
    assert all(curve.state == CurveState.FITTED for curve in series.curves)
    assert series.metadata["palette"] == "Ocean"
    window.undo_stack.undo()
    assert all(curve.state == CurveState.FITTED for curve in series.curves)
    project.dirty = False
    window.close()
    app.processEvents()


def test_selected_palette_across_series_is_atomic_and_preserves_series_settings() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("selected palettes")
    first = Series("First", metadata={"palette": "Colourblind"})
    second = Series("Second", metadata={"palette": "Ocean"})
    curves = [
        Curve(f"curve {i}", [0., 1.], [float(i), float(i + 1)])
        for i in range(5)
    ]
    for curve in curves[:2]:
        first.add(curve)
    for curve in curves[2:]:
        second.add(curve)
    project.add_series(first)
    project.add_series(second)
    for curve in curves:
        curve.state = CurveState.FITTED
    project.dirty = False

    window = MainWindow(project)
    original = [curve.colour for curve in curves]
    metadata_before = [dict(series.metadata) for series in project.dataset.series]
    # Selected order is the visible tree order across both series.
    selected = [curves[0].id, curves[2].id, curves[4].id]
    count = window.undo_stack.count()
    window.apply_selected_palette(selected, "Ocean")
    expected = SERIES_PALETTES["Ocean"]
    assert [curves[i].colour for i in (0, 2, 4)] == list(expected[:3])
    assert [curves[i].colour for i in (1, 3)] == [original[1], original[3]]
    assert [dict(series.metadata) for series in project.dataset.series] == metadata_before
    assert all(curve.state == CurveState.FITTED for curve in curves)
    assert window.undo_stack.count() == count + 1

    window.undo_stack.undo()
    assert [curve.colour for curve in curves] == original
    window.undo_stack.redo()
    assert [curves[i].colour for i in (0, 2, 4)] == list(expected[:3])
    assert [dict(series.metadata) for series in project.dataset.series] == metadata_before

    window.apply_selected_palette(selected, "Ocean")
    assert window.undo_stack.count() == count + 1  # No-op palette is not recorded.
    window.apply_selected_palette(selected, "not a palette")
    assert window.undo_stack.count() == count + 1
    project.dirty = False
    window.close()
    app.processEvents()


def test_individual_spectrum_colour_picker_changes_non_red_colour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, curve, _ = _gaussian_project()
    curve.state = CurveState.FITTED
    project.dirty = False
    window = MainWindow(project)
    monkeypatch.setattr(
        QColorDialog,
        "getColor",
        lambda *args, **kwargs: QColor("#3455AA"),
    )
    window.choose_curve_colour(curve.id)
    assert curve.colour == "#3455AA"
    assert curve.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()


def test_visibility_colour_square_tracks_spectrum_colour_and_undo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    app = QApplication.instance() or QApplication([])
    project = Project("colour square")
    series = Series("Spectra")
    first = Curve("first", [0., 1.], [1., 2.])
    second = Curve("second", [0., 1.], [2., 3.])
    first.visible = False
    series.add(first)
    series.add(second)
    project.add_series(series)
    project.dirty = False
    window = MainWindow(project)
    window.show()
    tree = window.curve_tree
    tree.expandAll()
    app.processEvents()
    picker_calls = []

    def cancelled_picker(*args, **_kwargs):
        picker_calls.append(args[0].name().upper())
        return QColor()

    monkeypatch.setattr(QColorDialog, "getColor", cancelled_picker)

    def inspect(colour: str) -> None:
        item = tree.topLevelItem(0).child(0)
        index = tree.indexFromItem(item, 0)
        option = QStyleOptionViewItem()
        # A standalone style option has an invalid (-1, -1) decoration size.
        # Populate it as QTreeView does before querying Qt's icon rectangle.
        option.decorationSize = tree.iconSize()
        delegate = tree.itemDelegate(index)
        delegate.initStyleOption(option, index)
        option.rect = tree.visualRect(index)
        option.widget = tree
        checkbox = tree.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree
        )
        decoration = tree.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemDecoration, option, tree
        )
        assert item.checkState(0) == Qt.CheckState.Unchecked
        assert not item.icon(0).isNull()
        assert not decoration.isEmpty()
        assert decoration.left() > checkbox.right()
        assert decoration.right() <= option.rect.right()
        assert decoration.size() == checkbox.size()
        icon_image = item.icon(0).pixmap(tree.iconSize()).toImage()
        center = icon_image.rect().center()
        assert icon_image.pixelColor(center).name().upper() == colour
        app.processEvents()
        # Grab the real widget. A standalone delegate paint missed the clipping bug.
        image = tree.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        x = round(decoration.center().x() * scale)
        y = round(decoration.center().y() * scale)
        assert image.pixelColor(x, y).name().upper() == colour
        count = len(picker_calls)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=decoration.center())
        app.processEvents()
        assert picker_calls == [*picker_calls[:count], colour]
        assert not first.visible  # The swatch is not a second checkbox.

    inspect(first.colour.upper())
    window._set_curve_colour(first.id, "#009E73")
    inspect("#009E73")
    window.apply_series_palette(series.id, "Ocean")
    inspect(SERIES_PALETTES["Ocean"][0].upper())
    window.undo_stack.undo()
    inspect("#009E73")

    # An accepted choice changes the spectrum colour and remains undoable.
    monkeypatch.setattr(
        QColorDialog, "getColor", lambda *_args, **_kwargs: QColor("#3455AA")
    )
    item = tree.topLevelItem(0).child(0)
    index = tree.indexFromItem(item, 0)
    option = QStyleOptionViewItem()
    option.decorationSize = tree.iconSize()
    tree.itemDelegate(index).initStyleOption(option, index)
    option.rect = tree.visualRect(index)
    option.widget = tree
    swatch = tree.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemDecoration, option, tree
    )
    checkbox = tree.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree
    )
    assert not swatch.intersects(checkbox)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=swatch.center())
    app.processEvents()
    assert first.colour == "#3455AA"
    assert not first.visible
    window.undo_stack.undo()
    assert first.colour == "#009E73"
    window.undo_stack.redo()
    assert first.colour == "#3455AA"

    # The native checkbox still toggles visibility without changing colour.
    item = tree.topLevelItem(0).child(0)
    index = tree.indexFromItem(item, 0)
    option = QStyleOptionViewItem()
    option.decorationSize = tree.iconSize()
    tree.itemDelegate(index).initStyleOption(option, index)
    option.rect = tree.visualRect(index)
    option.widget = tree
    checkbox = tree.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree
    )
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=checkbox.center())
    app.processEvents()
    assert first.visible
    assert first.colour == "#3455AA"
    project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("gesture", ["slip", "double_click", "drag_then_click"])
def test_colour_square_owns_click_and_preserves_current_spectra(monkeypatch, gesture):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from curvemole.core.display import DisplayOptions

    app = QApplication.instance() or QApplication([])
    project = Project()
    for name in ("Active", "Selected", "Target"):
        curve = Curve(name, [0., 1., 2.], [2., 3., 4.])
        project.add_curve(curve)
        background = Component.create("constant", initial={"offset": 1.})
        background.is_background = True
        project.model_for(curve.id).add(background)
    active, selected, target = project.curves
    window = CurveMoleMainWindow(project)
    window.show()
    tree = window.curve_tree
    tree.expandAll()
    app.processEvents()
    viewport = tree.viewport()
    button = Qt.MouseButton.LeftButton
    parent = tree.topLevelItem(0)
    active_index = tree.indexFromItem(parent.child(0), 1)
    QTest.mouseClick(viewport, button, pos=tree.visualRect(active_index).center())
    parent.child(1).setSelected(True)
    controller = window.view_options_controller
    options = DisplayOptions(original=True)
    assert controller.apply({active.id: options})
    index = tree.indexFromItem(parent.child(2), 0)
    swatch = tree.itemDelegate().note_rect(index)
    original = target.colour
    picker_calls = []

    def pick(colour, *_args):
        picker_calls.append(colour.name().upper())
        assert controller.for_curve(active.id) == options
        return QColor("#3455AA")

    monkeypatch.setattr(QColorDialog, "getColor", pick)
    try:
        if gesture == "slip":
            edge = QPoint(swatch.right(), swatch.center().y())
            QTest.mousePress(viewport, button, pos=edge)
            QTest.mouseRelease(viewport, button, pos=edge + QPoint(1, 0))
        elif gesture == "double_click":
            QTest.mouseDClick(viewport, button, pos=swatch.center())
            QTest.mouseRelease(viewport, button, pos=swatch.center())
        else:
            outside = swatch.center() + QPoint(QApplication.startDragDistance() + swatch.width(), 0)
            QTest.mousePress(viewport, button, pos=swatch.center())
            QTest.mouseMove(viewport, outside)
            QTest.mouseRelease(viewport, button, pos=outside)
            assert tree._dragged_row is None
            assert not picker_calls
            QTest.mouseClick(viewport, button, pos=swatch.center())

        assert picker_calls == [original.upper()]
        assert window.active_curve_id == active.id
        assert tree.selected_curve_ids() == {active.id, selected.id}
        assert controller.for_curve(active.id) == options
        assert target.colour == "#3455AA"
    finally:
        project.dirty = False
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(
    ("fit_colour", "too_close", "chosen"),
    [(MODEL_SUM_COLOUR, "#D82A2A", "#FF0000"), ("#0055AA", "#0356A9", MODEL_SUM_COLOUR)],
)
def test_colour_picker_compares_with_the_current_fit_colour(monkeypatch, fit_colour, too_close, chosen):
    app = QApplication.instance() or QApplication([])
    project, curve, _ = _gaussian_project()
    window = MainWindow(project)
    appearance = window.plot_workspace.plot_appearance()
    appearance["model_sum_colour"] = fit_colour
    window.plot_workspace.set_plot_appearance(appearance)
    choices = iter((QColor(too_close), QColor(chosen)))
    warnings = []
    monkeypatch.setattr(QColorDialog, "getColor", lambda *_args: next(choices))
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    try:
        window.choose_curve_colour(curve.id)
        assert curve.colour == chosen
        assert len(warnings) == 1 and fit_colour in warnings[0]
    finally:
        project.dirty = False
        window.close()
        app.processEvents()


def test_existing_spectrum_colours_are_preserved_on_open() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("old red")
    colours = ["#FF0000", MODEL_SUM_COLOUR]
    for index, colour in enumerate(colours):
        curve = Curve(str(index), [0.0, 1.0], [0.0, 1.0])
        curve.colour = colour
        project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)
    try:
        assert [curve.colour for curve in project.curves] == colours
        assert not project.dirty
    finally:
        project.dirty = False
        window.close()
        app.processEvents()
