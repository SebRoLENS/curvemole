"""Window-scoped shortcuts and discoverable tooltips for menu/toolbar commands."""
from __future__ import annotations

import json
import string
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractButton, QMenu, QToolBar, QToolButton
from shiboken6 import isValid

_PREFERRED = {
    "quit_action": "Ctrl+Q",
    "quick_peak_action": "Ctrl+Shift+A",
    "quick_fit_action": "Ctrl+F5",
    "cancel_action": "Ctrl+Shift+F5",
    "resume_action": "Shift+F5",
    "copy_fit_action": "Ctrl+Shift+C",
    "copy_fit_next_action": "Ctrl+Alt+C",
    "find_peaks_action": "Ctrl+Shift+P",
    "function_info_action": "Ctrl+Shift+F1",
    "function_action": "Ctrl+Shift+F",
    "calculator_action": "Ctrl+Shift+D",
    "notebook_action": "Ctrl+Shift+N",
    "uncertainty_action": "Ctrl+Shift+U",
    "export_parameters_action": "Ctrl+Alt+E",
    "export_view_action": "Ctrl+Alt+V",
    "portable_action": "Ctrl+Alt+S",
    "plugins_action": "Ctrl+Shift+M",
    "auto_axes_action": "Ctrl+Shift+V",
    "manual_action": "Ctrl+Shift+H",
}


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
            self.saved = saved if isinstance(saved, dict) else {}
        except (ValueError, TypeError):
            self.saved = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def schedule(self):
        if not self.updating and not self.timer.isActive():
            self.timer.start(0)

    def eventFilter(self, watched, event):
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
            used = {_portable(seq) for action in self.window.findChildren(QAction)
                    for seq in action.shortcuts() if not seq.isEmpty()}
            used.update(_portable(seq) for shortcut in self.window.findChildren(QShortcut) for seq in shortcut.keys())  # noqa: SIM118
            used.update(_portable(button.shortcut()) for button in self.window.findChildren(QAbstractButton) if not button.shortcut().isEmpty())
            names = {action: name for name, action in vars(self.window).items() if isinstance(action, QAction)}
            # Aliases refer to the same command, so prefer the named assignment above.
            for name in _PREFERRED:
                action = getattr(self.window, name, None)
                if isinstance(action, QAction):
                    names[action] = name
            # Reserve an uncommon chord prefix. Each complete sequence is unique.
            keys = [*string.ascii_uppercase, *string.digits, *(f"F{i}" for i in range(1, 13)),
                    "Home", "End", "PgUp", "PgDown", "Insert", "Delete", "Left", "Right", "Up", "Down"]
            available = (prefix + ", " + modifier + key
                         for prefix in ("Ctrl+K", "Ctrl+Alt+Shift+K") if prefix not in used
                         for modifier in ("", "Shift+", "Ctrl+", "Alt+", "Ctrl+Shift+", "Alt+Shift+")
                         for key in keys)
            saved_before = dict(self.saved)
            identities = [names.get(action) or self.identities.get(action, action.text()) for action in actions]
            identities += ["button/" + (button.objectName() or button.text()) for button in self.buttons()]
            reserved = {self.saved[identity] for identity in identities if isinstance(self.saved.get(identity), str)}
            for action in actions:
                identity = names.get(action) or self.identities.get(action, action.text())
                if not action.shortcuts():
                    preferred = _PREFERRED.get(names.get(action))
                    if preferred and _portable(QKeySequence(preferred)) not in used:
                        sequence = QKeySequence(preferred)
                    elif isinstance(self.saved.get(identity), str) and self.saved[identity] not in used and not QKeySequence(self.saved[identity]).isEmpty():
                        sequence = QKeySequence(self.saved[identity])
                    else:
                        sequence = next(QKeySequence(candidate) for candidate in available
                                        if _portable(QKeySequence(candidate)) not in used | reserved)
                    action.setShortcut(sequence)
                    action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
                    used.add(_portable(sequence))
                    self.saved[identity] = _portable(sequence)
                if action.menu() is not None and action not in self.menu_actions:
                    action.triggered.connect(self.open_command_menu)
                    self.menu_actions.add(action)
                action.setShortcutVisibleInContextMenu(True)
                self._tooltip(action)
            for button in self.buttons():
                self._watch(button)
                identity = "button/" + (button.objectName() or button.text())
                if button.shortcut().isEmpty():
                    saved = self.saved.get(identity)
                    if isinstance(saved, str) and saved not in used and not QKeySequence(saved).isEmpty():
                        sequence = QKeySequence(saved)
                    else:
                        sequence = next(QKeySequence(candidate) for candidate in available
                                        if _portable(QKeySequence(candidate)) not in used | reserved)
                    button.setShortcut(sequence)
                    used.add(_portable(sequence))
                    self.saved[identity] = _portable(sequence)
                self._tooltip(button)
            if self.saved != saved_before:
                self.window.settings.setValue("shortcuts/commands", json.dumps(self.saved))
        finally:
            self.updating = False


def install_action_shortcuts(window):
    window._action_shortcuts = ActionShortcuts(window)
