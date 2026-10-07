from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("Quick Add finish gestures")
    curve = Curve("Spectrum", list(range(9)), [0, 0, 0.5, 2, 4, 2, 0.5, 0, 0])
    project.add_curve(curve)
    main = CurveMoleMainWindow(project)
    main.resize(1400, 850)
    main.show()
    main.activateWindow()
    app.processEvents()
    main.plot_workspace.view_box.setRange(xRange=(-1, 9), yRange=(-1, 5), padding=0)
    yield app, main, curve
    project.dirty = False
    main.close()
    main.deleteLater()
    app.processEvents()


def _click_point(app, workspace, x, y, button=Qt.MouseButton.LeftButton):
    pos = workspace.graphics.mapFromScene(workspace.view_box.mapViewToScene(QPointF(x, y)))
    assert workspace.graphics.viewport().rect().contains(pos)
    QTest.mouseClick(workspace.graphics.viewport(), button, pos=pos)
    app.processEvents()


def _start_quick_add(app, main, function_id, *, manual_points=True):
    main.settings.setValue(f"quick_add_controls/{function_id}/manual_points", manual_points)
    main.settings.setValue(f"quick_add_controls/{function_id}/background", False)
    main.quick_function_selector.setCurrentIndex(main.quick_function_selector.findData(function_id))
    main.quick_peak()
    main.plot_workspace.graphics.setFocus()
    app.processEvents()


def _finish_gesture(app, workspace, gesture):
    if gesture == "right-click":
        _click_point(app, workspace, 4, 1, Qt.MouseButton.RightButton)
    elif gesture == "return":
        QTest.keyClick(workspace.graphics.viewport(), Qt.Key.Key_Return)
    else:
        QTest.keyClick(
            workspace.graphics.viewport(), Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier
        )
    app.processEvents()


def _assert_gestures_inactive(workspace):
    assert workspace._placement_mode is None
    assert not workspace._quick_add_placement
    assert not workspace.view_box.quick_add_placement
    assert not workspace._quick_add_return.isEnabled()
    assert not workspace._quick_add_enter.isEnabled()


@pytest.mark.parametrize("gesture", ["right-click", "return", "numpad-enter"])
@pytest.mark.parametrize("function_id", ["linear", "gaussian", "cubic_spline"])
def test_finish_gesture_commits_quick_add_points(window, function_id, gesture):
    app, main, curve = window
    workspace = main.plot_workspace
    _start_quick_add(app, main, function_id)
    for x, y in [(2, 0.5), (4, 3.5), (6, 0.5)]:
        _click_point(app, workspace, x, y)
    assert workspace.finish_placement_button.isEnabled()

    _finish_gesture(app, workspace, gesture)

    components = main.project.model_for(curve.id).components
    assert len(components) == 1
    assert components[0].function_id == function_id
    _assert_gestures_inactive(workspace)
    assert main._pending_component is None


@pytest.mark.parametrize("gesture", ["right-click", "return", "numpad-enter"])
@pytest.mark.parametrize("function_id", ["linear", "gaussian", "cubic_spline"])
def test_finish_gesture_with_too_few_points_keeps_quick_add_active(window, function_id, gesture):
    app, main, curve = window
    workspace = main.plot_workspace
    _start_quick_add(app, main, function_id)
    _click_point(app, workspace, 2, 0.5)
    before = list(workspace._spline_points)
    assert not workspace.finish_placement_button.isEnabled()

    _finish_gesture(app, workspace, gesture)

    assert workspace._placement_mode == "spline"
    assert workspace._quick_add_placement
    assert workspace._spline_points == before
    assert not main.project.model_for(curve.id).components
    assert not workspace.view_box._context_menu_timer.isActive()
    workspace.cancel_placement()
    _assert_gestures_inactive(workspace)


@pytest.mark.parametrize("gesture", ["right-click", "return", "numpad-enter"])
def test_finish_gesture_stops_continuous_quick_peak_and_keeps_added_peaks(window, gesture):
    app, main, curve = window
    workspace = main.plot_workspace
    _start_quick_add(app, main, "gaussian", manual_points=False)
    _click_point(app, workspace, 2, 3)
    _click_point(app, workspace, 6, 2)
    assert workspace._continuous_peak_placement
    assert len(main.project.model_for(curve.id).components) == 2

    _finish_gesture(app, workspace, gesture)

    assert len(main.project.model_for(curve.id).components) == 2
    assert not workspace._continuous_peak_placement
    assert main._pending_component is None
    _assert_gestures_inactive(workspace)


@pytest.mark.parametrize("manual_points", [False, True])
def test_regular_point_placement_keeps_right_click_point_removal(window, manual_points):
    app, main, _ = window
    workspace = main.plot_workspace
    if manual_points:
        workspace.begin_manual_point_placement("Linear", "linear", 2)
    else:
        workspace.begin_spline_placement("Spline")
    app.processEvents()
    for x, y in [(2, 0.5), (4, 3.5), (6, 0.5)]:
        _click_point(app, workspace, x, y)

    _click_point(app, workspace, 4, 3.5, Qt.MouseButton.RightButton)

    assert workspace._placement_mode == "spline"
    assert len(workspace._spline_points) == 2
    assert all(abs(x - 4) > 1 for x, _ in workspace._spline_points)
    assert not workspace._quick_add_return.isEnabled()
    assert not workspace._quick_add_enter.isEnabled()
    workspace.cancel_placement()


def test_idle_right_click_opens_normal_plot_menu_after_quick_add_finishes(window):
    app, main, _ = window
    workspace = main.plot_workspace
    _start_quick_add(app, main, "gaussian", manual_points=False)
    _finish_gesture(app, workspace, "return")
    _assert_gestures_inactive(workspace)
    menu = workspace.view_box.getMenu(None)
    shown = QSignalSpy(menu.aboutToShow)
    try:
        _click_point(app, workspace, 4, 1, Qt.MouseButton.RightButton)

        assert workspace.view_box._context_menu_timer.isActive() or shown.count()
        if not shown.count():
            assert shown.wait(QApplication.doubleClickInterval() + 2000)
        app.processEvents()
        assert menu.isVisible()
    finally:
        workspace.view_box._context_menu_timer.stop()
        workspace.view_box._context_menu_event = None
        menu.close()
        app.processEvents()


def test_idle_right_click_masks_a_point_after_quick_add_cancels(window):
    app, main, curve = window
    workspace = main.plot_workspace
    _start_quick_add(app, main, "linear")
    workspace.cancel_placement()
    workspace.mask_toggle.setChecked(True)
    app.processEvents()

    _click_point(app, workspace, 4, 1, Qt.MouseButton.RightButton)

    assert main.project.dataset.curve(curve.id).effective_mask[4]
    assert not workspace.view_box._context_menu_timer.isActive()


@pytest.mark.parametrize("gesture", ["return", "numpad-enter"])
def test_enter_reaches_focused_control_after_quick_add_ends(window, gesture):
    app, main, _ = window
    workspace = main.plot_workspace
    _start_quick_add(app, main, "gaussian", manual_points=False)
    _finish_gesture(app, workspace, gesture)
    field = QLineEdit(workspace)
    workspace.layout().addWidget(field)
    submitted = []
    field.returnPressed.connect(lambda: submitted.append(True))
    field.show()
    field.setFocus()
    app.processEvents()

    key = Qt.Key.Key_Return if gesture == "return" else Qt.Key.Key_Enter
    modifiers = (
        Qt.KeyboardModifier.NoModifier
        if gesture == "return"
        else Qt.KeyboardModifier.KeypadModifier
    )
    QTest.keyClick(field, key, modifiers)
    app.processEvents()

    assert submitted == [True]
