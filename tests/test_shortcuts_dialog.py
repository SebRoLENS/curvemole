from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog

from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.shortcuts_dialog import ShortcutsDialog


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "shortcuts.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("curvemole.gui.main_window.QSettings", lambda *args: settings)
    window = CurveMoleMainWindow()
    app.processEvents()
    yield window
    window.project.dirty = False
    window.close()
    app.processEvents()


def _rows(dialog):
    return [tuple(dialog.keyboard.item(row, col).text() for col in range(3))
            for row in range(dialog.keyboard.rowCount())]


def test_help_action_opens_mouse_and_keyboard_reference(window, monkeypatch):
    opened = []

    def inspect(dialog):
        assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["Mouse", "Keyboard"]
        assert "Right double-click" in dialog.mouse.toPlainText()
        assert "Mask mode" in dialog.mouse.toPlainText()
        save_key = QKeySequence("Ctrl+S").toString(QKeySequence.SequenceFormat.NativeText)
        assert save_key in {row[1] for row in _rows(dialog)}
        opened.append(dialog)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ShortcutsDialog, "exec", inspect)
    assert window.shortcuts_action in window.help_menu.actions()
    window.shortcuts_action.trigger()
    assert len(opened) == 1


def test_keyboard_reference_includes_current_commands_buttons_and_plugins(window):
    plugin = QAction("Example plugin command", window)
    window.tools_menu.addAction(plugin)
    dialog = ShortcutsDialog(window, "Mouse gestures")
    try:
        rows = _rows(dialog)
        for command in (*window._action_shortcuts.commands(), *window._action_shortcuts.buttons()):
            keys = command.shortcuts() if isinstance(command, QAction) else [command.shortcut()]
            for key in keys:
                if not key.isEmpty():
                    native = key.toString(QKeySequence.SequenceFormat.NativeText)
                    assert any(native in row[1].split(", ") for row in rows), command.text()
        assert any(row[0] == "Example plugin command" and "Tools" in row[2] for row in rows)
        delete_key = QKeySequence("Delete").toString(QKeySequence.SequenceFormat.NativeText)
        assert any(row[1] == delete_key and row[2] == "Edit data points" for row in rows)
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("query", ["save project", None, "edit data points"],
                         ids=["command", "native-shortcut", "context"])
def test_keyboard_search_matches_commands_keys_and_contexts(window, query):
    if query is None:
        query = QKeySequence("Ctrl+S").toString(QKeySequence.SequenceFormat.NativeText).casefold()
    dialog = ShortcutsDialog(window, "Mouse gestures")
    try:
        dialog.search.setText(query)
        dialog.keyboard.sortItems(1)
        visible = [row for i, row in enumerate(_rows(dialog)) if not dialog.keyboard.isRowHidden(i)]
        assert visible
        assert all(any(query in value.casefold() for value in row) for row in visible)
        dialog.search.clear()
        assert not any(dialog.keyboard.isRowHidden(i) for i in range(dialog.keyboard.rowCount()))
    finally:
        dialog.deleteLater()
