from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QFileDialog

from curvemole import Component, Curve, Project
from curvemole.core.fitting import FitMode, FitPlan, FitSettings
from curvemole.gui.dialogs import (
    CopyFitDialog,
    FitPlanDialog,
    ImportMappingDialog,
    ParameterLinkDialog,
)
from curvemole.gui.main_window import (
    MainWindow,
    _semantic_version,
    _update_kind,
    _update_notification_due,
)
from curvemole.gui.plot import MaskViewBox
from curvemole.version import __version__


def test_main_window_starts_offscreen() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle().endswith(f"CurveMole {__version__}")
    assert window.plot_workspace is not None
    window.close()
    app.processEvents()


def test_update_version_classification_and_reminder_policy() -> None:
    current = _semantic_version("v1.2.3")
    assert current == (1, 2, 3)
    assert _update_kind(current, (1, 2, 4)) == "patch"
    assert _update_kind(current, (1, 3, 0)) == "minor"
    assert _update_kind(current, (2, 0, 0)) == "major"

    day = 24 * 60 * 60
    assert _update_notification_due("1.2.4", "", 0.0, 100.0)
    assert not _update_notification_due("1.2.4", "1.2.4", 100.0, 100.0 + 9 * day)
    assert _update_notification_due("1.2.4", "1.2.4", 100.0, 100.0 + 10 * day)
    # A still newer release bypasses the ten-day quiet period immediately.
    assert _update_notification_due("1.2.5", "1.2.4", 100.0, 101.0)


def test_file_actions_do_not_forward_qaction_checked_state(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    calls = {"open": 0, "import": 0}

    def fake_open(*args: object, **kwargs: object) -> tuple[str, str]:
        calls["open"] += 1
        return "", ""

    def fake_import(*args: object, **kwargs: object) -> tuple[list[str], str]:
        calls["import"] += 1
        return [], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_open)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", fake_import)

    window.open_action.trigger()
    window.import_action.trigger()

    assert calls == {"open": 1, "import": 1}
    window.close()
    app.processEvents()


def test_quick_peak_reuses_last_peak_function() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Quick peak")
    curve = Curve("curve", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)
    window.last_peak_function_id = "lorentzian"

    window.quick_peak()

    assert window._pending_component is not None
    assert window._pending_component.function_id == "lorentzian"
    assert window.plot_workspace._placement_mode == "peak"
    window.plot_workspace.cancel_placement()
    project.dirty = False
    window.close()
    app.processEvents()


def test_quick_fit_reuses_settings_on_current_curve(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Quick fit")
    curve = Curve("curve", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)
    previous = FitPlan(["old-curve-id"])
    previous.settings.loss = "huber"
    window.last_fit_plan = previous
    plans: list[FitPlan] = []
    monkeypatch.setattr(window, "_run_fit", lambda plan: plans.append(plan))

    window.quick_fit()

    assert len(plans) == 1
    assert plans[0].curve_ids == [curve.id]
    assert plans[0].settings.loss == "huber"
    project.dirty = False
    window.close()
    app.processEvents()


def test_component_selection_refresh_does_not_recurse() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Selection")
    curve = Curve("curve", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    project.add_curve(curve)
    component = Component.create("gaussian")
    project.model_for(curve.id).add(component)
    project.dirty = False
    window = MainWindow(project)

    window._set_component(component.id)

    assert window.model_panel.selected_component_id() == component.id
    assert window.model_panel.parameters.rowCount() == 3
    window.close()
    app.processEvents()


def test_graphical_peak_and_spline_placement_create_components() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Placement")
    curve = Curve(
        "curve",
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [1.0, 2.0, 5.0, 2.0, 1.0],
    )
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)

    window._pending_component = Component.create("gaussian")
    window._pending_component_curve_id = curve.id
    window._graphical_peak_placed(2.0, 5.0, 1.2)
    peak = project.model_for(curve.id).components[0]
    assert peak.parameters["center"].value == 2.0
    assert 2.354820045 * peak.parameters["sigma"].value == pytest.approx(1.2)

    window._pending_component = Component.create(
        "cubic_spline", metadata={"x_nodes": [0.0, 4.0]}
    )
    window._pending_component_curve_id = curve.id
    window._graphical_spline_placed([(0.0, 1.0), (2.0, 1.2), (4.0, 1.0)])
    spline = project.model_for(curve.id).components[1]
    assert spline.metadata["x_nodes"] == [0.0, 2.0, 4.0]

    project.dirty = False
    window.close()
    app.processEvents()


def test_right_drag_requests_interval_mask() -> None:
    class TestViewBox(MaskViewBox):
        def mapSceneToView(self, point: QPointF) -> QPointF:
            return point

    class DragEvent:
        accepted = False

        def button(self) -> Qt.MouseButton:
            return Qt.MouseButton.RightButton

        def isFinish(self) -> bool:
            return True

        def buttonDownScenePos(self) -> QPointF:
            return QPointF(1.25, 0.0)

        def scenePos(self) -> QPointF:
            return QPointF(4.75, 0.0)

        def accept(self) -> None:
            self.accepted = True

    view_box = TestViewBox()
    requested: list[tuple[float, float]] = []
    view_box.maskRangeRequested.connect(lambda lower, upper: requested.append((lower, upper)))
    event = DragEvent()

    view_box.mouseDragEvent(event)

    assert requested == [(1.25, 4.75)]
    assert event.accepted


def test_spline_click_contract() -> None:
    class TestViewBox(MaskViewBox):
        def mapSceneToView(self, point: QPointF) -> QPointF:
            return point

    class ClickEvent:
        accepted = False

        def __init__(self, button: Qt.MouseButton, point: QPointF, *, double: bool = False) -> None:
            self._button = button
            self._point = point
            self._double = double

        def button(self) -> Qt.MouseButton:
            return self._button

        def scenePos(self) -> QPointF:
            return self._point

        def double(self) -> bool:
            return self._double

        def accept(self) -> None:
            self.accepted = True

    view_box = TestViewBox()
    view_box.interaction_mode = "spline"
    added: list[tuple[float, float]] = []
    removed: list[tuple[float, float]] = []
    finished: list[bool] = []
    view_box.splinePointRequested.connect(lambda x, y: added.append((x, y)))
    view_box.splinePointRemoveRequested.connect(lambda x, y: removed.append((x, y)))
    view_box.placementFinishRequested.connect(lambda: finished.append(True))

    left = ClickEvent(Qt.MouseButton.LeftButton, QPointF(1.0, 2.0))
    right = ClickEvent(Qt.MouseButton.RightButton, QPointF(3.0, 4.0))
    double_left = ClickEvent(Qt.MouseButton.LeftButton, QPointF(5.0, 6.0), double=True)
    view_box.mouseClickEvent(left)
    view_box.mouseClickEvent(right)
    view_box.mouseClickEvent(double_left)

    assert added == [(1.0, 2.0)]
    assert removed == [(3.0, 4.0)]
    assert finished == [True]
    assert left.accepted and right.accepted and double_left.accepted

def test_bulk_selection_controls(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Bulk selection")
    curves = [
        Curve(f"curve {index}", [0.0, 1.0, 2.0], [0.0, float(index), 0.0])
        for index in range(1, 4)
    ]
    for curve in curves:
        project.add_curve(curve)
    project.dirty = False

    window = MainWindow(project)
    window.curve_tree.select_all_curves()
    assert window.curve_tree.selected_curve_ids() == {curve.id for curve in curves}
    window.curve_tree.deselect_all_curves()
    assert window.curve_tree.selected_curve_ids() == set()

    fit = FitPlanDialog(project, set(), FitSettings())
    fit.deselect_all_curves_button.click()
    assert all(
        fit.curves.item(row, 0).checkState() == Qt.CheckState.Unchecked
        for row in range(fit.curves.rowCount())
    )
    fit.select_all_curves_button.click()
    assert all(
        fit.curves.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(fit.curves.rowCount())
    )

    copy_dialog = CopyFitDialog(project, curves[0].id)
    copy_dialog.select_all_targets_button.click()
    assert len(copy_dialog.choices()[0]) == 2
    copy_dialog.deselect_all_targets_button.click()
    assert copy_dialog.choices()[0] == []

    data = tmp_path / "multi.csv"
    data.write_text("x,y1,y2\n0,1,2\n1,2,3\n", encoding="utf-8")
    importer = ImportMappingDialog(data)
    importer.select_all_y_button.click()
    assert all(
        importer.y_columns.item(index).checkState() == Qt.CheckState.Checked
        for index in range(importer.y_columns.count())
    )
    importer.deselect_all_y_button.click()
    assert all(
        importer.y_columns.item(index).checkState() == Qt.CheckState.Unchecked
        for index in range(importer.y_columns.count())
    )

    project.dirty = False
    window.close()
    app.processEvents()


def test_parameter_link_picker_and_global_fit_requirement() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Links")
    first = Curve("Spectrum A", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    second = Curve("Spectrum B", [0.0, 1.0, 2.0], [0.0, 1.2, 0.0])
    project.add_curve(first)
    project.add_curve(second)
    first_peak = Component.create("gaussian", name="Peak A")
    second_peak = Component.create("gaussian", name="Peak B")
    project.model_for(first.id).add(first_peak)
    project.model_for(second.id).add(second_peak)

    dialog = ParameterLinkDialog(project, first.id, first_peak.id, "center")
    dialog.source_curve.setCurrentIndex(dialog.source_curve.findData(second.id))
    dialog.source_component.setCurrentIndex(dialog.source_component.findData(second_peak.id))
    dialog.source_parameter.setCurrentIndex(dialog.source_parameter.findData("center"))
    expected = f"${{{second.id}.{second_peak.id}.center}}"
    assert dialog.link_expression() == expected

    dialog.mode.setCurrentIndex(dialog.mode.findData("advanced"))
    dialog.advanced.setText("2 * ${source} + 1")
    assert dialog.link_expression() == f"2 * {expected} + 1"

    first_peak.parameters["center"].link = expected
    fit_dialog = FitPlanDialog(project, {first.id, second.id}, FitSettings())
    independent = fit_dialog.plan()
    independent.mode = FitMode.INDEPENDENT
    with pytest.raises(ValueError, match="Global simultaneous"):
        fit_dialog._validate_link_scope(independent)
    independent.mode = FitMode.GLOBAL
    fit_dialog._validate_link_scope(independent)
    app.processEvents()


def test_update_check_accepts_qnetworkreply_error_enum() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class FakeReply:
        deleted = False

        def error(self):
            return QNetworkReply.NetworkError.ConnectionRefusedError

        def errorString(self) -> str:
            return "offline"

        def deleteLater(self) -> None:
            self.deleted = True

    reply = FakeReply()
    window._update_reply = reply
    window._update_check_finished(reply, False)
    assert reply.deleted
    assert window._update_reply is None
    window.close()
    app.processEvents()
