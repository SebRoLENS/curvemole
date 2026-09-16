"""Nonblocking update checks and downloads for loaded community plugins."""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from curvemole.core.plugin_identity import provenance
from curvemole.core.plugin_updates import (
    CATALOG_URL,
    MAX_ARCHIVE_BYTES,
    PluginUpdate,
    available_updates,
    stage_update,
)
from curvemole.gui.updates import CHECK_INTERVAL_MS, UpdateController, semantic_version, update_kind
from curvemole.version import __version__


class PluginUpdateController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.plugins = window.plugin_manager
        self.settings = window.settings
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.updates = []
        self.unsupported = []
        self.queue = []
        self.errors = []
        self.busy = False
        self.dialog = None
        self.message = "Check for updates to loaded plugins."
        self.badge = QToolButton(window)
        self.badge.setText("Plugins")
        self.badge.clicked.connect(self.open)
        window.statusBar().addPermanentWidget(self.badge)
        self._refresh_badge()
        window.update_action.triggered.connect(lambda checked=False: self.check(force=True))
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        QTimer.singleShot(0, self.check)

    def _pending(self):
        return {key: record["metadata"]["version"]
                for key, record in self.plugins.installed.items()
                if key in self.plugins.loaded and record.get("enabled")
                and record["metadata"]["version"] != self.plugins.loaded[key].version}

    def _refresh_badge(self, error=False):
        pending = self._pending()
        self.badge.setVisible(bool(self.plugins.loaded))
        state = "error" if error else "current"
        if self.busy:
            state = "checking"
        elif self.updates:
            kinds = [update_kind(semantic_version(u.current), semantic_version(u.latest)) for u in self.updates]
            state = "major" if "major" in kinds else "minor" if "minor" in kinds else "patch"
        elif pending:
            state = "patch"
        self.badge.setStyleSheet(UpdateController._BADGE_STYLES[state])
        self.badge.setText(f"Plugins: {len(self.updates)} updates" if self.updates else
                           "Plugins: restart required" if pending else "Plugins")
        self.badge.setToolTip(self.message)

    def _fetch(self, url, limit, callback):
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"CurveMole/{__version__}".encode())
        request.setTransferTimeout(30_000)
        reply = self.network.get(request)
        self.reply = reply
        data = bytearray()
        too_large = False

        def consume():
            nonlocal too_large
            data.extend(bytes(reply.readAll()))
            if len(data) > limit and not too_large:
                too_large = True
                reply.abort()

        def finished():
            consume()
            error = ("Download exceeds the size limit." if too_large else reply.errorString()
                     if reply.error() != QNetworkReply.NetworkError.NoError else "")
            self.reply = None
            reply.deleteLater()
            callback(bytes(data), error)

        reply.readyRead.connect(consume)
        reply.finished.connect(finished)

    def check(self, *, force=False):
        if self.busy:
            return
        if not any(key not in self.plugins.errors for key in self.plugins.loaded):
            self.updates, self.unsupported = [], []
            self.message = "No loaded plugins to check."
            self._refresh()
            return
        self.busy = True
        self.message = "Checking updates for loaded plugins…"
        self._refresh()
        self._fetch(CATALOG_URL, 1024 * 1024,
                    lambda data, error: self._checked(data, error, force))

    def _checked(self, data, error, force):
        self.busy = False
        try:
            if error:
                raise ValueError(error)
            self.updates, self.unsupported = available_updates(self.plugins, json.loads(data))
            self.message = (f"{len(self.updates)} plugin update(s) available." if self.updates else
                            "Loaded community plugins are up to date." if not self.unsupported else
                            "No updates available for supported loaded plugins.")
            unseen = [u for u in self.updates if self.settings.value(
                f"plugin_updates/notified/{u.identifier}", "") != u.latest]
            self._refresh()
            if unseen or force:
                self.open(check=False)
                for update in self.updates:
                    self.settings.setValue(f"plugin_updates/notified/{update.identifier}", update.latest)
        except Exception as exc:
            self.message = f"Could not check plugin updates: {exc}"
            self.window._log(self.message)
            self._refresh(error=True)
            if force:
                self.open(check=False)

    def open(self, checked=False, *, check=True):
        if self.dialog is None:
            dialog = QDialog(self.window)
            self.dialog = dialog
            dialog.setWindowTitle("Plugin updates")
            dialog.resize(800, 440)
            layout = QVBoxLayout(dialog)
            help_text = QLabel(
                "Only loaded plugins are checked against the validated Community Plugins catalog. "
                "Update selected downloads and trusts the listed versions. They become active when "
                "you reopen CurveMole; current fits and monitoring continue with the running versions."
            )
            help_text.setWordWrap(True)
            layout.addWidget(help_text)
            self.status = QLabel()
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["Plugin", "Running", "Available", "Status"])
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            buttons = QHBoxLayout()
            self.check_button = QPushButton("Check now")
            self.check_button.clicked.connect(lambda: self.check(force=True))
            self.update_button = QPushButton("Update selected")
            self.update_button.clicked.connect(self.install_selected)
            close = QPushButton("Close")
            close.clicked.connect(dialog.hide)
            for button in (self.check_button, self.update_button, close):
                buttons.addWidget(button)
            layout.addLayout(buttons)
        self._refresh()
        self.dialog.show()
        self.dialog.raise_()
        if check:
            self.check()

    def _refresh(self, error=False):
        self._refresh_badge(error)
        if self.dialog is None:
            return
        pending = self._pending()
        message = self.message
        if pending:
            message += "\nSave your project and reopen CurveMole to use installed updates."
        if self.unsupported:
            message += "\nNo automatic update source: " + ", ".join(self.unsupported)
        self.status.setText(message)
        self.check_button.setEnabled(not self.busy)
        self.update_button.setEnabled(not self.busy and any(u.compatible for u in self.updates))
        self.table.setRowCount(0)
        for update in self.updates:
            status = "Ready to update"
            if semantic_version(update.latest)[0] != semantic_version(update.current)[0]:
                status = "Major update — review compatibility"
            if not update.compatible:
                status = "Update CurveMole first"
            self._add_row(update.identifier, update.current, update.latest, status, update.compatible)
        for key, latest in pending.items():
            self._add_row(key, self.plugins.loaded[key].version, latest, "Installed — restart required", False)
        self.table.resizeColumnsToContents()

    def _add_row(self, identifier, current, latest, status, selectable):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((identifier, current, latest, status)):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if column == 0:
                symbol = self.plugins.symbol(identifier)
                name = self.plugins.plugin_name(identifier)
                item.setText(f"{symbol} {name}")
                item.setData(Qt.ItemDataRole.UserRole, identifier)
                item.setToolTip(provenance(symbol, name, identifier))
                if selectable:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, column, item)

    def install_selected(self):
        if self.busy:
            return
        selected = {self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())
                    if self.table.item(row, 0).checkState() == Qt.CheckState.Checked}
        self.queue = [u for u in self.updates if u.identifier in selected and u.compatible]
        if not self.queue:
            self.message = "Select at least one compatible plugin update."
            self._refresh()
            return
        self.errors = []
        self.busy = True
        self._download_next()

    def _download_next(self):
        if not self.queue:
            self.busy = False
            self.message = ("\n".join(self.errors) if self.errors else
                            "Selected updates installed. Reopen CurveMole to activate them.")
            self._refresh(error=bool(self.errors))
            return
        update = self.queue.pop(0)
        self.message = f"Downloading {update.name} {update.latest}…"
        self._refresh()
        self._fetch(update.url, MAX_ARCHIVE_BYTES,
                    lambda data, error: self._downloaded(update, data, error))

    def _downloaded(self, update: PluginUpdate, data, error):
        try:
            if error:
                raise ValueError(error)
            stage_update(self.plugins, update, data)
            self.updates = [u for u in self.updates if u.identifier != update.identifier]
        except Exception as exc:
            message = f"{update.identifier}: {exc}"
            self.errors.append(message)
            self.window._log(message)
        self._download_next()
