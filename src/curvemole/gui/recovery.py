"""Discoverable recovery choices, grouped by project rather than backup file."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    def __init__(self, manager, paths, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.selected_path = None
        self.setWindowTitle(self.tr("Recoverable sessions"))
        self.resize(650, 370)
        layout = QVBoxLayout(self)
        message = QLabel(self.tr(
            "Unsaved sessions are available, for example after an unexpected shutdown. "
            "Recover a session to continue working, decide later, or delete its recovery copies. "
            "Recovery does not overwrite the original project."
        ))
        message.setWordWrap(True)
        layout.addWidget(message)
        self.sessions = QTreeWidget()
        self.sessions.setHeaderLabels([self.tr("Project"), self.tr("Last recovery"), self.tr("Copies")])
        self.sessions.setRootIsDecorated(False)
        groups = {}
        for path in paths:
            project_id = path.name.split(".recovery-", 1)[0]
            groups.setdefault(project_id, []).append(path)
        for project_id, copies in groups.items():
            with zipfile.ZipFile(copies[0]) as archive:
                metadata = json.loads(archive.read("manifest.json"))["project"]
            item = QTreeWidgetItem(self.sessions, [metadata.get("name", project_id), self._date(copies[0]), str(len(copies))])
            item.setData(0, Qt.ItemDataRole.UserRole, (project_id, copies))
        self.sessions.header().setStretchLastSection(False)
        self.sessions.header().setSectionResizeMode(0, self.sessions.header().ResizeMode.Stretch)
        layout.addWidget(self.sessions)
        self.versions = QComboBox()
        self.versions.setToolTip(self.tr("The newest copy is selected; an older copy can also be recovered."))
        layout.addWidget(self.versions)
        buttons = QDialogButtonBox()
        self.recover_button = QPushButton(self.tr("Recover"))
        self.delete_button = QPushButton(self.tr("Delete recovery copies"))
        self.later_button = QPushButton(self.tr("Decide later"))
        buttons.addButton(self.recover_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.later_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.recover_button.clicked.connect(self._recover)
        self.delete_button.clicked.connect(self._delete)
        self.later_button.clicked.connect(self.reject)
        self.sessions.currentItemChanged.connect(self._selected)
        self.sessions.itemDoubleClicked.connect(lambda *_: self._recover())
        layout.addWidget(buttons)
        self.sessions.setCurrentItem(self.sessions.topLevelItem(0))

    @staticmethod
    def _date(path):
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _selected(self, item, *_):
        self.versions.clear()
        if item is not None:
            for path in item.data(0, Qt.ItemDataRole.UserRole)[1]:
                self.versions.addItem(self._date(path), path)
        self.recover_button.setEnabled(item is not None)
        self.delete_button.setEnabled(item is not None)

    def _recover(self):
        self.selected_path = self.versions.currentData()
        if self.selected_path is not None:
            self.accept()

    def _delete(self):
        item = self.sessions.currentItem()
        if item is None:
            return
        answer = QMessageBox.question(
            self, self.tr("Delete recovery copies"),
            self.tr("Delete all recovery copies for this session? The saved project will not be deleted."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.manager.clear(item.data(0, Qt.ItemDataRole.UserRole)[0])
        except OSError as exc:
            QMessageBox.warning(self, self.tr("Recovery cleanup failed"), str(exc))
            return
        self.sessions.takeTopLevelItem(self.sessions.indexOfTopLevelItem(item))
        if not self.sessions.topLevelItemCount():
            self.reject()
