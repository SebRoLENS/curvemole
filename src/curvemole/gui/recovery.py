"""Named, individually manageable recovery copies and explicit restore proposals."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class RecoveryDialog(QDialog):
    def __init__(self, manager, paths, parent=None, *, descriptions=None):
        super().__init__(parent)
        self.manager = manager
        self.selected_path = None
        self._descriptions = descriptions or {p: manager.description(p) for p in paths}
        self.setWindowTitle(self.tr("Recoverable sessions"))
        self.resize(880, 480)
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.sessions = QTreeWidget()
        self.sessions.setHeaderLabels([self.tr("Project / backup"), self.tr("Recovery date"), self.tr("Copies")])
        self.sessions.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        groups = {}
        for path in paths:
            project_id = path.name.split(".recovery-", 1)[0]
            groups.setdefault(project_id, []).append(path)
        for project_id, copies in groups.items():
            first_valid = next((p for p in copies if self._descriptions[p].get("valid", self._descriptions[p]["readable"])), copies[0])
            info = self._descriptions[first_valid]
            item = QTreeWidgetItem(self.sessions, [info["name"], self._date(copies[0]), str(len(copies))])
            item.setData(0, Qt.ItemDataRole.UserRole, (project_id, copies))
            for index, path in enumerate(copies, 1):
                suffix = self.tr(" (newest)") if index == 1 else ""
                if not self._descriptions[path].get("valid", self._descriptions[path]["readable"]):
                    suffix += self.tr(" (unreadable)")
                child = QTreeWidgetItem(item, [f"{info['name']} — {self.tr('backup')} {index}{suffix}", self._date(path), ""])
                child.setData(0, Qt.ItemDataRole.UserRole, (project_id, [path]))
                child.setToolTip(0, path.name)
        self.sessions.header().setStretchLastSection(False)
        self.sessions.header().setSectionResizeMode(0, self.sessions.header().ResizeMode.Stretch)
        layout.addWidget(self.sessions)
        self.versions = QComboBox()
        self.versions.setToolTip(self.tr("Choose a named backup; the newest valid copy is selected by default."))
        layout.addWidget(self.versions)
        buttons = QDialogButtonBox()
        self.recover_button = QPushButton(self.tr("Recover"))
        self.delete_button = QPushButton(self.tr("Delete selected copies"))
        self.later_button = QPushButton(self.tr("Decide later"))
        buttons.addButton(self.recover_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.later_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.recover_button.clicked.connect(self._recover)
        self.delete_button.clicked.connect(self._delete)
        self.later_button.clicked.connect(self.reject)
        self.sessions.currentItemChanged.connect(self._selected)
        self.versions.currentIndexChanged.connect(self._proposal)
        layout.addWidget(buttons)
        self.sessions.setCurrentItem(self.sessions.topLevelItem(0))

    @staticmethod
    def _date(path):
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _selected(self, item, *_):
        self.versions.blockSignals(True)
        self.versions.clear()
        if item is not None:
            root = item.parent() or item
            _project_id, copies = root.data(0, Qt.ItemDataRole.UserRole)
            for index, path in enumerate(copies, 1):
                name = self._descriptions[path]["name"]
                self.versions.addItem(f"{name} — {self.tr('backup')} {index} — {self._date(path)}", path)
            selected = item.data(0, Qt.ItemDataRole.UserRole)[1][0]
            if item.parent() is None:
                selected = next((p for p in copies if self._descriptions[p].get("valid", self._descriptions[p]["readable"])), selected)
            self.versions.setCurrentIndex(copies.index(selected))
        self.versions.blockSignals(False)
        self.delete_button.setEnabled(item is not None)
        self._proposal()

    def _proposal(self, *_):
        path = self.versions.currentData()
        if path is None:
            self.recover_button.setEnabled(False)
            self.message.setText(self.tr("No recovery copies selected."))
            return
        info = self._descriptions[path]
        source = info["source_file"] or info["name"]
        self.message.setText(self.tr(
            'Restore "{source}" from "{backup}"?\nRecovery file: {file}\n'
            'The original project will not be overwritten. Decide later keeps this proposal for the next launch.'
        ).format(source=source, backup=self.versions.currentText(), file=path.name))
        self.recover_button.setEnabled(info.get("valid", info["readable"]))

    def _recover(self):
        if self.recover_button.isEnabled():
            self.selected_path = self.versions.currentData()
            self.accept()

    def _delete(self):
        items = self.sessions.selectedItems()
        if not items and self.sessions.currentItem() is not None:
            items = [self.sessions.currentItem()]
        paths = list(dict.fromkeys(p for item in items for p in item.data(0, Qt.ItemDataRole.UserRole)[1]))
        if not paths:
            return
        answer = QMessageBox.question(
            self, self.tr("Delete recovery copies"),
            self.tr("Delete {count} selected recovery copy/copies? The saved project will not be deleted.").format(count=len(paths)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            empty = self.manager.delete_copies(paths)
            window = self.parent()
            session = getattr(window, "_recovery_session", None)
            if session is not None:
                for project_id in empty:
                    session.resolve(project_id)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.tr("Recovery cleanup failed"), str(exc))
            return
        removed = set(paths)
        for index in reversed(range(self.sessions.topLevelItemCount())):
            root = self.sessions.topLevelItem(index)
            project_id, copies = root.data(0, Qt.ItemDataRole.UserRole)
            remaining = [p for p in copies if p not in removed]
            if not remaining:
                self.sessions.takeTopLevelItem(index)
                continue
            root.setData(0, Qt.ItemDataRole.UserRole, (project_id, remaining))
            root.setText(1, self._date(remaining[0]))
            root.setText(2, str(len(remaining)))
            for child_index in reversed(range(root.childCount())):
                if root.child(child_index).data(0, Qt.ItemDataRole.UserRole)[1][0] in removed:
                    root.takeChild(child_index)
            for child_index in range(root.childCount()):
                root.child(child_index).setText(0, f"{root.text(0)} — {self.tr('backup')} {child_index + 1}")
        if window is not None and hasattr(window, "_monitor_recovery_count"):
            window._monitor_recovery_count()
        if self.sessions.topLevelItemCount() == 0:
            self.reject()
        else:
            self.sessions.setCurrentItem(self.sessions.topLevelItem(0))
            self._selected(self.sessions.currentItem())
