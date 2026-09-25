from __future__ import annotations

from curvemole.core.models import Component, Model
from curvemole.core.registry import default_registry
from curvemole.core.reorder import reorder_component_names


def test_reorder_uses_selected_parameter_separately_for_each_function_type():
    registry = default_registry()
    components = [
        Component.create("gaussian", registry=registry,
                         initial={"center": center, "area": area})
        for center, area in [(3, 10), (1, 30), (2, 20)]
    ] + [
        Component.create("voigt", registry=registry, initial={"center": center})
        for center in [4, -1]
    ]
    for index, component in enumerate(components[:3], 1):
        component.name = f"Gaussian{index}"
    for index, component in enumerate(components[3:], 1):
        component.name = f"Voigt{index}"
    model = Model(components=components)
    identities = [component.id for component in model.components]

    assert reorder_component_names(model, registry, {"gaussian": "center", "voigt": "center"}) == 5
    assert [component.name for component in components] == [
        "Gaussian3", "Gaussian1", "Gaussian2", "Voigt2", "Voigt1"]
    assert [component.id for component in model.components] == identities

    reorder_component_names(model, registry, {"gaussian": "area", "voigt": "center"})
    assert [component.name for component in components[:3]] == [
        "Gaussian1", "Gaussian3", "Gaussian2"]


def test_reorder_leaves_custom_names_untouched_and_reserves_their_numbers():
    registry = default_registry()
    custom = Component.create("gaussian", initial={"center": -1})
    custom.name = "Gaussian1"
    custom.metadata["custom_name"] = True
    high = Component.create("gaussian", initial={"center": 2})
    low = Component.create("gaussian", initial={"center": 0})
    high.name, low.name = "Gaussian2", "Gaussian3"
    model = Model(components=[custom, high, low])

    assert reorder_component_names(model, registry, {"gaussian": "center"}) == 2
    assert [item.name for item in model.components] == ["Gaussian1", "Gaussian3", "Gaussian2"]
    assert reorder_component_names(model, registry, {"gaussian": "center"}) == 0


def test_reorder_button_renames_without_invalidating_fit_and_can_undo(tmp_path):
    import numpy as np
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from curvemole.core.data import Curve, CurveState
    from curvemole.core.project import Project
    from curvemole.gui.main_window import MainWindow
    from curvemole.gui.reorder import ReorderRulesDialog, load_reorder_rules

    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("example", np.arange(4.0), np.ones(4))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    for center in (2, 1):
        component = Component.create("gaussian", initial={"center": center})
        component.name = f"Gaussian{len(model.components) + 1}"
        model.add(component)
    curve.state = CurveState.FITTED
    window = MainWindow(project)
    window.settings = QSettings(str(tmp_path / "reorder.ini"), QSettings.Format.IniFormat)
    assert window.model_panel.reorder_button.text() == "Reorder"
    rules_dialog = ReorderRulesDialog(model, default_registry(), {}, window)
    assert rules_dialog.fields["gaussian"].currentText() == "center"
    rules_dialog.fields["gaussian"].setCurrentText("area")
    assert rules_dialog.rules()["gaussian"] == "area"
    rules_dialog.close()
    assert load_reorder_rules(window.settings) == {}
    window.model_panel.reorder_button.click()
    assert [item.name for item in project.model_for(curve.id).components] == ["Gaussian2", "Gaussian1"]
    assert curve.state == CurveState.FITTED
    window.undo_stack.undo()
    assert [item.name for item in project.model_for(curve.id).components] == ["Gaussian1", "Gaussian2"]
    assert curve.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()
