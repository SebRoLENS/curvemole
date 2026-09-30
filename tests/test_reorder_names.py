from __future__ import annotations

from curvemole.core.models import Component, Model
from curvemole.core.registry import default_registry
from curvemole.core.reorder import reorder_component_names


def test_reorder_sorts_custom_names_stably_and_keeps_unsortable_slots():
    registry = default_registry()
    high = Component.create("gaussian", initial={"center": 3})
    background = Component.create("constant")
    low = Component.create("lorentzian", initial={"center": 1})
    tied = Component.create("gaussian", initial={"center": 1})
    invalid = Component.create("gaussian", initial={"center": float("inf")})
    for item in (high, low, tied, invalid):
        item.metadata["custom_name"] = True
    original = [high, background, low, tied, invalid]
    names = {item.id: item.name for item in original}
    model = Model(components=list(original))

    assert reorder_component_names(model, registry, {}) == 0
    assert [item.id for item in model.components] == [
        low.id, background.id, tied.id, high.id, invalid.id]
    assert {item.id: item.name for item in model.components} == names
    assert Model.from_dict(model.to_dict()).to_dict() == model.to_dict()


def test_reorder_button_sorts_when_names_already_match_and_invalidates_nonadditive_fit(tmp_path):
    import numpy as np
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from curvemole.core.data import Curve, CurveState
    from curvemole.core.project import Project
    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("example", np.arange(4.0), np.ones(4))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    background = Component.create("constant")
    high = Component.create("gaussian", name="Gaussian2", initial={"center": 2})
    low = Component.create("gaussian", name="Gaussian1", initial={"center": 1}, operator="multiply")
    model.components = [background, high, low]
    curve.state = CurveState.FITTED
    window = MainWindow(project)
    window.settings = QSettings(str(tmp_path / "reorder.ini"), QSettings.Format.IniFormat)

    window.model_panel.reorder_button.click()
    assert [item.id for item in project.model_for(curve.id).components] == [background.id, low.id, high.id]
    assert curve.state == CurveState.MODIFIED
    assert window.undo_stack.count() == 1
    window.model_panel.reorder_button.click()
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert [item.id for item in project.model_for(curve.id).components] == [background.id, high.id, low.id]
    project.dirty = False
    window.close()
    app.processEvents()


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
    model = Model(components=list(components))
    identities = [component.id for component in model.components]

    assert reorder_component_names(model, registry, {"gaussian": "center", "voigt": "center"}) == 5
    assert [component.name for component in components] == [
        "Gaussian3", "Gaussian1", "Gaussian2", "Voigt2", "Voigt1"]
    assert [component.id for component in model.components] == [identities[i] for i in (4, 1, 2, 0, 3)]
    assert [component.parameters["center"].value for component in model.components] == [-1, 1, 2, 3, 4]

    reorder_component_names(model, registry, {"gaussian": "area", "voigt": "center"})
    assert [component.name for component in components[:3]] == [
        "Gaussian1", "Gaussian3", "Gaussian2"]
    assert [component.id for component in model.components] == [identities[i] for i in (4, 3, 0, 2, 1)]


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
    assert [item.name for item in model.components] == ["Gaussian1", "Gaussian2", "Gaussian3"]
    assert [item.id for item in model.components] == [custom.id, low.id, high.id]
    assert reorder_component_names(model, registry, {"gaussian": "center"}) == 0


def test_reorder_button_renames_without_invalidating_fit_and_can_undo(tmp_path):
    import numpy as np
    from PySide6.QtCore import QSettings, Qt
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
    identities = [item.id for item in model.components]
    expected_y = model.evaluate(curve.x)
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
    assert [item.name for item in project.model_for(curve.id).components] == ["Gaussian1", "Gaussian2"]
    assert [item.id for item in project.model_for(curve.id).components] == identities[::-1]
    assert [window.model_panel.components.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(2)] == identities[::-1]
    np.testing.assert_allclose(project.model_for(curve.id).evaluate(curve.x), expected_y)
    assert curve.state == CurveState.FITTED
    window.undo_stack.undo()
    assert [item.name for item in project.model_for(curve.id).components] == ["Gaussian1", "Gaussian2"]
    assert [item.id for item in project.model_for(curve.id).components] == identities
    window.undo_stack.redo()
    assert [item.id for item in project.model_for(curve.id).components] == identities[::-1]
    assert curve.state == CurveState.FITTED
    project.dirty = False
    window.close()
    app.processEvents()
