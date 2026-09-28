from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

from curvemole import Component, Curve, Project
from curvemole.core.functions import formula_definition
from curvemole.core.plugins import export_custom_function
from curvemole.core.registry import default_registry
from curvemole.gui import app as gui_app  # noqa: F401 - installs GUI compatibility patches
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import PlotWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project(name: str = "Quick functions") -> tuple[Project, Curve]:
    project = Project(name)
    curve = Curve(
        "curve",
        list(range(9)),
        [0.0, 0.0, 1.0, 4.0, 10.0, 4.0, 1.0, 0.0, 0.0],
    )
    project.add_curve(curve)
    project.dirty = False
    return project, curve


def test_quick_add_selector_lists_the_complete_registry() -> None:
    app = _app()
    window = MainWindow()

    identifiers = {
        str(window.quick_function_selector.itemData(index))
        for index in range(window.quick_function_selector.count())
    }
    assert identifiers == set(window.registry.identifiers())
    assert window.quick_peak_action.text() == "Quick Add Function"

    window.close()
    app.processEvents()


def test_quick_add_can_add_a_generic_function() -> None:
    app = _app()
    project, curve = _project()
    window = MainWindow(project)

    index = window.quick_function_selector.findData("linear")
    assert index >= 0
    window.quick_function_selector.setCurrentIndex(index)
    window.quick_peak()

    assert window.plot_workspace._placement_mode == "spline"
    assert window.plot_workspace._manual_points_active
    assert not project.model_for(curve.id).components
    window.plot_workspace._add_spline_point(0.0, 1.0)
    window.plot_workspace._add_spline_point(2.0, 5.0)
    window.plot_workspace.finish_placement()

    components = project.model_for(curve.id).components
    assert len(components) == 1
    assert components[0].function_id == "linear"
    assert components[0].parameters["slope"].value == pytest.approx(2.0)
    assert components[0].parameters["intercept"].value == pytest.approx(1.0)
    assert all(parameter.fixed for parameter in components[0].parameters.values())
    assert window.settings.value("last_quick_function") == "linear"

    project.dirty = False
    window.close()
    app.processEvents()


def test_manual_placement_clicks_pass_through_plot_points_and_previews() -> None:
    app = _app()
    project, curve = _project("Manual placement over points")
    component = Component.create("linear")
    project.model_for(curve.id).add(component)
    window = MainWindow(project)
    workspace = window.plot_workspace
    workspace.set_plot_appearance({"data_style": "points", "function_style": "points"})
    data = workspace._data_items[curve.id]
    model = workspace._component_items[component.id]
    original_data = data.scatter.acceptedMouseButtons()
    original_model = model.scatter.acceptedMouseButtons()
    assert original_data != Qt.MouseButton.NoButton

    workspace.begin_manual_point_placement("Linear", "linear", 2)
    assert data.scatter.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert model.scatter.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert model.curve.acceptedMouseButtons() == Qt.MouseButton.NoButton
    workspace._add_spline_point(2.0, 1.0)
    assert workspace._placement_items[0].scatter.acceptedMouseButtons() == Qt.MouseButton.NoButton

    workspace.refresh()  # A redraw must keep newly created symbols transparent.
    assert workspace._data_items[curve.id].scatter.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert workspace._component_items[component.id].scatter.acceptedMouseButtons() == Qt.MouseButton.NoButton
    data = workspace._data_items[curve.id]
    model = workspace._component_items[component.id]
    workspace.cancel_placement()
    assert data.scatter.acceptedMouseButtons() == original_data
    assert model.scatter.acceptedMouseButtons() == original_model

    workspace.begin_peak_placement("Gaussian")
    assert data.scatter.acceptedMouseButtons() == Qt.MouseButton.NoButton
    workspace.cancel_placement()
    project.dirty = False
    window.close()
    app.processEvents()


def test_click_exactly_on_visible_data_symbol_places_manual_point() -> None:
    app = _app()
    project, curve = _project("Click on a data symbol")
    workspace = PlotWorkspace(default_registry())
    workspace.resize(1100, 750)
    workspace.show()
    workspace.set_context(project, curve.id)
    workspace.set_plot_appearance({"data_style": "points", "data_point_size": 28})
    app.processEvents()
    workspace.view_box.setRange(xRange=(-1, 9), yRange=(-1, 11), padding=0)
    workspace.begin_manual_point_placement("Linear", "linear", 2)
    app.processEvents()

    # (3, 4) is an experimental point. Exercise real scene dispatch, since
    # pyqtgraph symbols can intercept a click even with NoButton set.
    target = workspace.graphics.mapFromScene(
        workspace.view_box.mapViewToScene(QPointF(3.0, 4.0))
    )
    QTest.mouseClick(workspace.graphics.viewport(), Qt.MouseButton.LeftButton, pos=target)
    app.processEvents()
    assert len(workspace._spline_points) == 1
    assert workspace._spline_points[0] == pytest.approx((3.0, 4.0), abs=0.1)

    workspace.close()
    app.processEvents()


def test_automatic_peak_search_uses_selected_peak_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    project, curve = _project("Peak search")
    window = MainWindow(project)

    answers = iter(
        [
            ("Positive (default)", True),
            (window.registry.get("lorentzian").display_name, True),
        ]
    )
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: next(answers))
    def choose_function(dialog):
        dialog.setTextValue(window.registry.get("lorentzian").display_name)
        return 1
    monkeypatch.setattr(QInputDialog, "exec", choose_function)
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (1, True))

    window.find_peaks()

    components = project.model_for(curve.id).components
    assert len(components) == 1
    assert components[0].function_id == "lorentzian"

    project.dirty = False
    window.close()
    app.processEvents()


def test_reusable_function_library_is_loaded_from_configured_folder(tmp_path) -> None:
    app = _app()
    window = MainWindow()
    directory = tmp_path / "my_curvemole_functions"
    directory.mkdir()
    identifier = "persistent_test_peak"
    definition = formula_definition(
        identifier,
        "Persistent test peak",
        "amplitude * exp(-0.5*((x-center)/sigma)**2)",
        kind="peak",
    )
    export_custom_function(definition, directory / f"{identifier}.curvemole-function.json")

    previous = window.settings.value("custom_function_directory")
    try:
        window.settings.setValue("custom_function_directory", str(directory))
        window._load_user_function_library()

        assert window.registry.get(identifier).display_name == "Persistent test peak"
        assert window.quick_function_selector.findData(identifier) >= 0
    finally:
        if identifier in window.registry.identifiers():
            window.registry.unregister(identifier)
        if previous is None:
            window.settings.remove("custom_function_directory")
        else:
            window.settings.setValue("custom_function_directory", previous)

    window.close()
    app.processEvents()
