"""Window-scoped shortcuts and discoverable tooltips for menu/toolbar commands."""
from __future__ import annotations

import json
import string
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTableView,
    QTextEdit,
    QToolBar,
    QToolButton,
)
from shiboken6 import isValid

_PREFERRED = {
    "new_action": "Ctrl+N", "open_action": "Ctrl+O", "import_action": "Ctrl+I",
    "save_action": "Ctrl+S", "save_as_action": "S", "export_action": "Ctrl+E",
    "quit_action": "Ctrl+Q", "undo_action": "Ctrl+Z", "redo_action": "Ctrl+Y",
    "add_component_action": "Ctrl+A", "quick_add_function_action": "A",
    "edit_points_action": "E", "fit_action": "Ctrl+F", "quick_fit_action": "F",
    "cancel_action": "X", "resume_action": "C", "copy_fit_action": "Ctrl+C",
    "copy_fit_next_action": "Ctrl+V", "find_peaks_action": "Ctrl+P",
    "function_info_action": "H", "function_action": "Ctrl+H",
    "calculator_action": "D", "notebook_action": "N", "uncertainty_action": "Ctrl+U",
    "subtract_background_action": "B", "revert_background_action": "R",
    "auto_axes_action": "V", "view_options_action": "O", "restore_original_action": "U",
    "manual_action": "Ctrl+M", "quick_start_action": "Ctrl+J",
    "quick_add_background": "G", "quick_add_manual_points": "P",
    "export_spectra_action": "Ctrl+T",
}
_PREFERRED_TEXT = {"Mask": "M", "View unmasked": "W", "Run automation": "T"}
_SHORTCUT_SCHEMA = 2


def _simple(sequence):
    if sequence.count() != 1:
        return False
    key = sequence[0]
    return (key.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
            and not Qt.Key.Key_F1 <= key.key() <= Qt.Key.Key_F35
            or key.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier
            and Qt.Key.Key_A <= key.key() <= Qt.Key.Key_Z)


def _portable(sequence):
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


class ActionShortcuts(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.updating = False
        self.watched = weakref.WeakSet()
        self.tooltips = weakref.WeakKeyDictionary()
        self.identities = weakref.WeakKeyDictionary()
        self.menu_actions = weakref.WeakSet()
        try:
            saved = json.loads(str(window.settings.value("shortcuts/commands", "{}")))
            self.saved = (saved if isinstance(saved, dict)
                          and window.settings.value("shortcuts/schema", 0, type=int) == _SHORTCUT_SCHEMA else {})
        except (ValueError, TypeError):
            self.saved = {}
        self.bindings = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        QApplication.instance().installEventFilter(self)
        self.refresh()

    def schedule(self):
        if not self.updating and not self.timer.isActive():
            self.timer.start(0)

    def _typing(self):
        widget = QApplication.focusWidget()
        while widget is not None and widget is not self.window:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QTableView)):
                return True
            if isinstance(widget, QComboBox):
                return True
            widget = widget.parentWidget()
        return False

    def _key_command(self, event):
        if (QApplication.activeWindow() is not self.window
                or QApplication.activePopupWidget() is not None
                or QApplication.activeModalWidget() not in (None, self.window)):
            return None
        sequence = QKeySequence(event.keyCombination())
        command = self.bindings.get(_portable(sequence))
        if command is None or not isValid(command) or not command.isEnabled():
            return None
        # Typing and the editor's native copy/paste/undo/navigation take priority.
        if self._typing() and (event.modifiers() == Qt.KeyboardModifier.NoModifier
                               or _portable(sequence) in {"Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+Y"}):
            return None
        return command

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            if (QApplication.activeWindow() is not self.window
                    or QApplication.activePopupWidget() is not None
                    or QApplication.activeModalWidget() not in (None, self.window)):
                return False
            command = self._key_command(event)
            if command is not None:
                event.accept()
                if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                    command.trigger() if isinstance(command, QAction) else command.click()
                return True
            # Let editors consume plain keys even when the underlying widget
            # would otherwise let a window QAction claim its shortcut.
            if event.type() == QEvent.Type.ShortcutOverride and self._typing():
                sequence = _portable(QKeySequence(event.keyCombination()))
                if sequence in self.bindings:
                    event.accept()
                    return True
        if watched not in self.watched:
            return False
        if event.type() in {QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved, QEvent.Type.ActionChanged, QEvent.Type.ChildAdded}:
            self.schedule()
        elif event.type() == QEvent.Type.ToolTip:
            self.refresh()
        return False

    def _watch(self, widget):
        if widget not in self.watched:
            widget.installEventFilter(self)
            self.watched.add(widget)

    def commands(self):
        result = []
        seen = set()

        def visit(widget, path=()):
            self._watch(widget)
            if isinstance(widget, QMenu):
                widget.setToolTipsVisible(True)
            for action in widget.actions():
                if action.menu() is not None:
                    if action.menu() not in seen:
                        seen.add(action.menu())
                        visit(action.menu(), (*path, action.text()))
                elif not action.isSeparator() and action.text().strip() and action not in seen:
                    seen.add(action)
                    result.append(action)
                    self.identities.setdefault(action, "/".join((*path, action.text())))

        visit(self.window.menuBar())
        for toolbar in self.window.findChildren(QToolBar):
            visit(toolbar, (toolbar.objectName(),))
            for button in toolbar.findChildren(QToolButton):
                self._watch(button)
                action = button.defaultAction()
                if action is not None and not action.isSeparator() and action not in seen:
                    seen.add(action)
                    result.append(action)
                    self.identities.setdefault(action, "/".join((toolbar.objectName(), action.text())))
                if button.menu() is not None and button.menu() not in seen:
                    seen.add(button.menu())
                    visit(button.menu(), (toolbar.objectName(), button.text()))
        return result

    def buttons(self):
        return [button for toolbar in self.window.findChildren(QToolBar)
                for button in toolbar.findChildren(QAbstractButton)
                if button.text().strip() and (not isinstance(button, QToolButton) or button.defaultAction() is None)
                and button.objectName() != "qt_toolbar_ext_button"]

    def _tooltip(self, action):
        shortcuts = action.shortcuts() if isinstance(action, QAction) else [action.shortcut()]
        sequences = [seq.toString(QKeySequence.SequenceFormat.NativeText) for seq in shortcuts if not seq.isEmpty()]
        if not sequences:
            return
        raw = action.toolTip()
        previous = self.tooltips.get(action)
        original = previous[0] if previous and previous[1] == raw else raw
        name = action.text().replace("&&", "\0").replace("&", "").replace("\0", "&").split("\t")[0]
        description = original
        if description.split("\n", 1)[0].rstrip(".…") == name.rstrip(".…"):
            description = description.partition("\n")[2]
        decorated = f"{name} ({', '.join(sequences)})"
        if description:
            decorated += "\n" + description
        self.tooltips[action] = (original, decorated)
        if raw != decorated:
            action.setToolTip(decorated)
        for widget in action.associatedObjects() if isinstance(action, QAction) else ():
            if isinstance(widget, QToolButton):
                widget.setToolTip(decorated)

    def open_command_menu(self, checked=False):
        action = self.sender()
        if not isinstance(action, QAction) or action.menu() is None:
            return
        menu = action.menu()
        button = next((widget for widget in action.associatedObjects()
                       if isinstance(widget, QToolButton) and widget.isVisible()), None)
        position = (button.mapToGlobal(QPoint(0, button.height())) if button is not None
                    else self.window.mapToGlobal(QPoint(20, self.window.menuBar().height())))
        menu.popup(position)

    def refresh(self):
        if self.updating or not isValid(self.window):
            return
        self.updating = True
        try:
            actions = self.commands()
            buttons = self.buttons()
            commands = [*actions, *buttons]
            names = {action: name for name, action in vars(self.window).items()
                     if isinstance(action, (QAction, QAbstractButton))}
            for name in _PREFERRED:
                action = getattr(self.window, name, None)
                if isinstance(action, (QAction, QAbstractButton)):
                    names[action] = name
            identities = {action: (names.get(action) or self.identities.get(action, action.text()))
                          for action in commands}
            reserved = set(_PREFERRED.values()) | set(_PREFERRED_TEXT.values())
            # Startup menus are rebuilt in a platform-dependent order. Reserve
            # saved keys only for commands present now, not removed identities.
            reserved.update(self.saved[identity] for identity in identities.values()
                            if isinstance(self.saved.get(identity), str)
                            and _simple(QKeySequence(self.saved[identity])))
            # Prefer unmodified letters, then Ctrl+letter, digits and punctuation.
            pool = [*string.ascii_uppercase, *("Ctrl+"+c for c in string.ascii_uppercase),
                    *string.digits, "-", "+", ",", ".", "/", "*", ";", "'", "[", "]", "\\", "=", "`", ":", "Space"]
            available = iter(pool)
            used = set()
            saved_before = dict(self.saved)
            self.bindings = {}
            for command in commands:
                identity = identities[command]
                preferred = _PREFERRED.get(names.get(command)) or _PREFERRED_TEXT.get(command.text())
                saved = self.saved.get(identity)
                if preferred and preferred not in used:
                    key = preferred
                elif isinstance(saved, str) and _simple(QKeySequence(saved)) and saved not in used | set(_PREFERRED.values()) | set(_PREFERRED_TEXT.values()):
                    key = saved
                else:
                    key = next((candidate for candidate in available if candidate not in used | reserved), None)
                    if key is None:
                        # Additional plugins may exceed the single-key alphabet.
                        # Continue with Ctrl+digit rather than function-key chords.
                        key = next(("Ctrl+"+c for c in string.digits if "Ctrl+"+c not in used), None)
                    if key is None:
                        continue
                sequence = QKeySequence(key)
                used.add(_portable(sequence))
                self.saved[identity] = _portable(sequence)
                self.bindings[_portable(sequence)] = command
                if isinstance(command, QAction):
                    # A menu or a hidden toolbar button alone is not a reliable
                    # shortcut owner. Register every command on the main window.
                    if command not in self.window.actions():
                        self.window.addAction(command)
                    command.setShortcuts([sequence])
                    command.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
                    if command.menu() is not None and command not in self.menu_actions:
                        command.triggered.connect(self.open_command_menu)
                        self.menu_actions.add(command)
                    command.setShortcutVisibleInContextMenu(True)
                else:
                    self._watch(command)
                    command.setShortcut(sequence)
                self._tooltip(command)
            self.window.settings.setValue("shortcuts/schema", _SHORTCUT_SCHEMA)
            if self.saved != saved_before:
                self.window.settings.setValue("shortcuts/commands", json.dumps(self.saved))
        finally:
            self.updating = False


def install_action_shortcuts(window):
    window._action_shortcuts = ActionShortcuts(window)
