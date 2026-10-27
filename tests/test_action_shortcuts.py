from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "keys.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    project = Project("keys")
    project.add_curve(Curve("curve", np.arange(4.), np.arange(4.)))
    win = CurveMoleMainWindow(project)
    win.show()
    app.processEvents()
    yield app, win
    win.project.dirty = False
    win.close()
    app.processEvents()


def test_all_menu_and_toolbar_commands_have_unique_shortcuts_and_tooltips(window):
    _, win = window
    manager = win._action_shortcuts
    manager.refresh()
    seen = {}
    commands = manager.commands()
    assert len(commands) > 40
    for action in commands:
        assert not action.shortcut().isEmpty(), action.text()
        for seq in action.shortcuts():
            key = seq.toString()
            assert key not in seen or seen[key] is action, (key, seen.get(key), action.text())
            seen[key] = action
        native = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        assert native in action.toolTip().splitlines()[0]
    for toolbar in win.findChildren(QToolBar):
        for button in toolbar.findChildren(QToolButton):
            action = button.defaultAction()
            if action is not None:
                assert action.shortcut().toString(QKeySequence.SequenceFormat.NativeText) in button.toolTip()
    for button in manager.buttons():
        assert not button.shortcut().isEmpty()
        assert button.shortcut().toString() not in seen
        seen[button.shortcut().toString()] = button
        assert button.shortcut().toString(QKeySequence.SequenceFormat.NativeText) in button.toolTip()
    assert win.save_action.shortcut() == QKeySequence("Ctrl+S")
    assert win.fit_action.shortcut() == QKeySequence("F5")


def test_shortcuts_trigger_toolbar_and_menu_actions(window):
    app, win = window
    received = []
    for action in (win.quick_peak_action, win.manual_action, win.log_action):
        action.triggered.disconnect()
        name = action.text()
        action.triggered.connect(lambda checked=False, name=name: received.append(name))
        action.setEnabled(True)
        win.activateWindow()
        win.setFocus()
        app.processEvents()
        QTest.keySequence(win, action.shortcut())
        app.processEvents()
        assert received[-1] == action.text()


def test_dynamic_actions_and_changed_tooltips_are_updated(window):
    app, win = window
    menu = win.menuBar().actions()[0].menu()
    action = QAction("Plugin command", win)
    action.setToolTip("An explanation that must survive.")
    menu.addAction(action)
    app.processEvents()
    assert not action.shortcut().isEmpty()
    assert "An explanation" in action.toolTip()
    action.setText("Updated command")
    app.processEvents()
    assert action.toolTip().startswith("Updated command (")
    assert "An explanation" in action.toolTip()
    before = action.toolTip()
    win._action_shortcuts.refresh()
    assert action.toolTip() == before


def test_toolbar_toggles_have_working_shortcuts(window):
    app, win = window
    for checkbox in (win.quick_add_background, win.quick_add_manual_points):
        before = checkbox.isChecked()
        win.activateWindow()
        win.setFocus()
        app.processEvents()
        QTest.keySequence(win, checkbox.shortcut())
        QTest.qWait(150)
        app.processEvents()
        assert checkbox.isChecked() != before


def test_assigned_shortcuts_survive_reopening_with_new_commands(window):
    app, win = window
    first = win.log_action.shortcut()
    old_settings = win.settings
    second = CurveMoleMainWindow()
    second.settings = old_settings
    # Force restoration against the same settings while creating commands in a different order.
    for action in second._action_shortcuts.commands():
        if action is second.log_action:
            action.setShortcut(QKeySequence())
    second._action_shortcuts.saved = dict(win._action_shortcuts.saved)
    extra = QAction("An additional plugin command", second)
    second.menuBar().actions()[0].menu().insertAction(second.menuBar().actions()[0].menu().actions()[0], extra)
    second._action_shortcuts.refresh()
    assert second.log_action.shortcut() == first
    second.project.dirty = False
    second.close()
    app.processEvents()


def test_shortcut_opens_toolbar_drop_down_menus(window):
    app, win = window
    for action in (win.view_options_action, win.restore_original_action):
        win.activateWindow()
        win.setFocus()
        app.processEvents()
        QTest.keySequence(win, action.shortcut())
        app.processEvents()
        assert action.menu().isVisible()
        action.menu().close()
        app.processEvents()
