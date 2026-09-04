from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QInputDialog

from curvemole import Curve, Project
from curvemole.core.functions import formula_definition
from curvemole.core.plugins import export_custom_function
from curvemole.gui import app as gui_app  # noqa: F401 - installs GUI compatibility patches
from curvemole.gui.main_window import MainWindow


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

    components = project.model_for(curve.id).components
    assert len(components) == 1
    assert components[0].function_id == "linear"
    assert window.settings.value("last_quick_function") == "linear"

    project.dirty = False
    window.close()
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
