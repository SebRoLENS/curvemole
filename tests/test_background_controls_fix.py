from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QDialog, QToolBar

from curvemole import Component, Curve, Model, Project
from curvemole.core.calculator import apply_scalar
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import BackgroundComponentsDialog


def _two_background_curves() -> tuple[Project, list[np.ndarray], list[Component]]:
    project = Project("background controls")
    originals: list[np.ndarray] = []
    backgrounds: list[Component] = []
    for index, offset in enumerate((2.0, 5.0)):
        x = np.linspace(0.0, 4.0, 21)
        curve = Curve(f"spectrum {index}", x, offset + np.linspace(1.0, 2.0, len(x)))
        project.add_curve(curve)
        background = Component.create("constant", initial={"offset": offset})
        background.is_background = True
        project.model_for(curve.id).add(background)
        originals.append(curve.y.copy())
        backgrounds.append(background)
    project.dirty = False
    return project, originals, backgrounds


def test_background_dialog_apply_all_is_present_and_off_by_default() -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _ = _two_background_curves()
    curve = project.curves[0]
    window = CurveMoleMainWindow(project)
    dialog = BackgroundComponentsDialog(project, curve.id, window.registry)
    assert dialog.apply_to_all_spectra.isChecked() is False
    dialog.close()
    project.dirty = False
    window.close()
    app.processEvents()


def test_subtract_background_default_changes_only_current_spectrum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, originals, backgrounds = _two_background_curves()
    window = CurveMoleMainWindow(project)

    def accept(dialog: BackgroundComponentsDialog) -> QDialog.DialogCode:
        assert dialog.apply_to_all_spectra.isChecked() is False
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BackgroundComponentsDialog, "exec", accept)
    window.subtract_background()
    app.processEvents()

    np.testing.assert_allclose(project.curves[0].y, originals[0] - 2.0)
    np.testing.assert_allclose(project.curves[1].y, originals[1])
    assert backgrounds[0].enabled is False
    assert backgrounds[1].enabled is True

    project.dirty = False
    window.close()
    app.processEvents()


def test_apply_all_checkbox_uses_all_marked_backgrounds_on_all_spectra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, originals, backgrounds = _two_background_curves()
    window = CurveMoleMainWindow(project)

    def accept(dialog: BackgroundComponentsDialog) -> QDialog.DialogCode:
        dialog.apply_to_all_spectra.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BackgroundComponentsDialog, "exec", accept)
    window.subtract_background()
    app.processEvents()

    for curve, original, offset, background in zip(
        project.curves,
        originals,
        (2.0, 5.0),
        backgrounds,
        strict=True,
    ):
        np.testing.assert_allclose(curve.y, original - offset)
        assert background.is_background is True
        assert background.enabled is False

    project.dirty = False
    window.close()
    app.processEvents()


def test_revert_background_is_selective_and_preserves_other_transformations() -> None:
    app = QApplication.instance() or QApplication([])
    project, originals, backgrounds = _two_background_curves()
    window = CurveMoleMainWindow(project)
    window.subtract_all_backgrounds()
    app.processEvents()

    apply_scalar(project.curves[0], "y_add", 1.5)
    window.revert_backgrounds([project.curves[0].id])
    app.processEvents()

    np.testing.assert_allclose(project.curves[0].y, originals[0] + 1.5)
    np.testing.assert_allclose(project.curves[1].y, originals[1] - 5.0)
    assert backgrounds[0].enabled is True
    assert backgrounds[1].enabled is False
    assert all(
        transformation.parameters.get("method") != "model_components_global"
        for transformation in project.curves[0].transformations
    )
    assert any(
        transformation.parameters.get("method") == "model_components_global"
        for transformation in project.curves[1].transformations
    )

    window.undo_stack.undo()
    app.processEvents()
    np.testing.assert_allclose(project.curves[0].y, originals[0] - 2.0 + 1.5)
    assert backgrounds[0].enabled is False

    project.dirty = False
    window.close()
    app.processEvents()


def test_undo_background_after_model_replacement_restores_live_functions() -> None:
    app = QApplication.instance() or QApplication([])
    project, originals, backgrounds = _two_background_curves()
    window = CurveMoleMainWindow(project)
    window.subtract_all_backgrounds()
    first_id = project.curves[0].id
    subtraction = project.curves[0].transformations[-1]
    np.testing.assert_allclose(subtraction.operand, 2.0)

    before = project.model_for(first_id).to_dict()
    changed = Model.from_dict(before)
    changed.component(backgrounds[0].id).parameters["offset"].value = 9.0
    window._push_model_state(first_id, before, changed.to_dict(), "Edit background")
    window.undo_stack.undo()  # Replaces the model object with a saved copy.
    window.undo_stack.undo()  # Subtract backgrounds must restore that live copy.

    np.testing.assert_allclose(project.curves[0].y, originals[0])
    np.testing.assert_allclose(project.curves[1].y, originals[1])
    assert project.model_for(first_id).component(backgrounds[0].id).enabled
    assert project.model_for(project.curves[1].id).component(backgrounds[1].id).enabled

    project.dirty = False
    window.close()
    app.processEvents()


def test_single_background_undo_uses_saved_values_after_model_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    project, originals, backgrounds = _two_background_curves()
    window = CurveMoleMainWindow(project)
    monkeypatch.setattr(
        BackgroundComponentsDialog,
        "exec",
        lambda _dialog: QDialog.DialogCode.Accepted,
    )
    window.subtract_background()
    curve_id = project.curves[0].id
    before = project.model_for(curve_id).to_dict()
    changed = Model.from_dict(before)
    changed.component(backgrounds[0].id).parameters["offset"].value = 9.0
    window._push_model_state(curve_id, before, changed.to_dict(), "Edit background")
    window.undo_stack.undo()
    window.undo_stack.undo()

    np.testing.assert_allclose(project.curves[0].y, originals[0])
    assert project.model_for(curve_id).component(backgrounds[0].id).enabled
    window.undo_stack.redo()
    np.testing.assert_allclose(project.curves[0].y, originals[0] - 2.0)
    assert not project.model_for(curve_id).component(backgrounds[0].id).enabled

    project.dirty = False
    window.close()
    app.processEvents()


def test_revert_background_keeps_later_fit_parameters_but_restores_original_data() -> None:
    app = QApplication.instance() or QApplication([])
    project, originals, backgrounds = _two_background_curves()
    window = CurveMoleMainWindow(project)
    window.subtract_all_backgrounds()
    curve_id = project.curves[0].id
    model = project.model_for(curve_id)
    model.component(backgrounds[0].id).parameters["offset"].value = 9.0

    window.revert_backgrounds([curve_id])

    np.testing.assert_allclose(project.curves[0].y, originals[0])
    assert model.component(backgrounds[0].id).parameters["offset"].value == 9.0
    assert not project.curves[0].transformations

    project.dirty = False
    window.close()
    app.processEvents()


def test_old_standalone_global_button_is_removed_and_revert_button_is_present() -> None:
    app = QApplication.instance() or QApplication([])
    project, _, _ = _two_background_curves()
    window = CurveMoleMainWindow(project)
    toolbar = window.findChild(QToolBar, "Main_toolbar")
    assert toolbar is not None
    assert window.subtract_all_backgrounds_action not in toolbar.actions()
    assert window.revert_background_action in toolbar.actions()
    assert window.background_subtracted_view_action in toolbar.actions()
    assert toolbar.actions().index(window.background_subtracted_view_action) < toolbar.actions().index(window.revert_background_action)
    assert window.background_subtracted_view_action.isCheckable()

    project.dirty = False
    window.close()
    app.processEvents()
