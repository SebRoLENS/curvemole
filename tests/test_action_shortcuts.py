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


def _with_shortcut(commands):
    return [command for command in commands if not command.shortcut().isEmpty()]


def test_documented_commands_have_unique_shortcuts_shown_in_tooltips(window):
    from curvemole.gui.action_shortcuts import _PREFERRED

    _, win = window
    manager = win._action_shortcuts
    manager.refresh()
    for name, key in _PREFERRED.items():
        action = getattr(win, name, None)
        if action is not None:
            assert action.shortcut() == QKeySequence(key), name
    seen = {}
    for command in _with_shortcut([*manager.commands(), *manager.buttons()]):
        key = command.shortcut().toString()
        assert key not in seen or seen[key] is command, (key, seen.get(key), command.text())
        seen[key] = command
        native = command.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        assert native in command.toolTip().splitlines()[0]
    for toolbar in win.findChildren(QToolBar):
        for button in toolbar.findChildren(QToolButton):
            action = button.defaultAction()
            if action is not None and not action.shortcut().isEmpty():
                assert action.shortcut().toString(QKeySequence.SequenceFormat.NativeText) in button.toolTip()


def test_system_conventions_are_respected(window):
    _, win = window
    manager = win._action_shortcuts
    assigned = {command.shortcut().toString() for command in _with_shortcut(
        [*manager.commands(), *manager.buttons()])}
    # Select all, copy, paste, cut and close keep their usual meaning.
    assert not assigned & {"Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+W", "Ctrl+P"}
    assert win.save_action.shortcut() == QKeySequence("Ctrl+S")
    assert win.save_as_action.shortcut() == QKeySequence("Ctrl+Shift+S")
    assert win.fit_action.shortcut() == QKeySequence("Ctrl+F")
    # Commands that change data or the layout never sit on a single key.
    for action in (win.save_as_action, win.restore_original_action, win.revert_background_action):
        sequence = action.shortcut()
        assert sequence.isEmpty() or sequence[0].keyboardModifiers() != 0, action.text()
    # No digits or punctuation: those differ between keyboard layouts.
    for key in assigned:
        assert len(key) != 1 or key.isalpha(), key


def test_shortcuts_trigger_toolbar_and_menu_actions(window):
    app, win = window
    received = []
    for action in (win.quick_fit_action, win.manual_action, win.calculator_action):
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


def test_new_commands_get_no_automatic_key_and_keep_their_tooltips(window):
    app, win = window
    before = {command: command.shortcut().toString() for command in win._action_shortcuts.commands()}
    menu = win.menuBar().actions()[0].menu()
    action = QAction("Plugin command", win)
    action.setToolTip("An explanation that must survive.")
    menu.addAction(action)
    for index in range(15):
        menu.addAction(QAction(f"Additional native command {index}", win))
    app.processEvents()
    win._action_shortcuts.refresh()
    assert action.shortcut().isEmpty()
    assert action.toolTip() == "An explanation that must survive."
    for command, key in before.items():
        assert command.shortcut().toString() == key, command.text()


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


def test_commands_work_with_plot_and_function_list_focus(window):
    app, win = window
    received = []
    action = win.manual_action
    action.triggered.disconnect()
    action.triggered.connect(lambda checked=False: received.append("manual"))
    action.setEnabled(True)
    for widget in (win.plot_workspace.graphics.viewport(), win.model_panel.components):
        win.activateWindow()
        widget.setFocus()
        app.processEvents()
        QTest.keySequence(widget, action.shortcut())
        app.processEvents()
        assert received
        received.clear()


def test_plain_shortcuts_do_not_steal_typing_or_native_select_all(window):
    from PySide6.QtWidgets import QLineEdit

    app, win = window
    editor = QLineEdit(win)
    editor.show()
    win.activateWindow()
    editor.setFocus()
    app.processEvents()
    received = []
    action = win.quick_add_function_action
    action.triggered.disconnect()
    action.triggered.connect(lambda checked=False: received.append("add"))
    action.setEnabled(True)
    QTest.keyClicks(editor, "a test")
    assert editor.text() == "a test"
    assert not received
    QTest.keySequence(editor, QKeySequence("Ctrl+A"))
    assert editor.selectedText() == "a test"


def test_shortcut_opens_toolbar_drop_down_menu(window):
    app, win = window
    action = win.view_options_action
    win.activateWindow()
    win.setFocus()
    app.processEvents()
    QTest.keySequence(win, action.shortcut())
    app.processEvents()
    assert action.menu().isVisible()
    action.menu().close()
    app.processEvents()


def test_previous_automatic_assignments_are_discarded(window):
    _, win = window
    manager = win._action_shortcuts
    manager.saved["manual_action"] = "Ctrl+K, F1"
    win.manual_action.setShortcut(QKeySequence("Ctrl+K, F1"))
    manager.refresh()
    assert win.manual_action.shortcut() == QKeySequence("Ctrl+M")
    assert win.settings.value("shortcuts/schema", type=int) == 3


def test_every_command_with_a_shortcut_activates_from_it(window):
    import warnings

    app, win = window
    actions = _with_shortcut(win._action_shortcuts.commands())
    assert len(actions) > 20
    received = []
    for action in actions:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            action.triggered.disconnect()
        action.triggered.connect(lambda checked=False, action=action: received.append(action))
        action.setEnabled(True)
    for action in actions:
        win.activateWindow()
        win.plot_workspace.graphics.setFocus()
        app.processEvents()
        received.clear()
        action.setEnabled(True)
        QTest.keySequence(win.plot_workspace.graphics, action.shortcut())
        app.processEvents()
        assert received == [action], (action.text(), action.shortcut().toString(), received)
