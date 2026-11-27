"""PluginManagerDialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.plugin_identity import provenance
from curvemole.core.plugins import PluginCandidate, PluginManager
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


class PluginManagerDialog(QDialog):
    def __init__(
        self,
        manager: PluginManager,
        directory: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.candidates: list[PluginCandidate] = []
        self.loaded_identifiers: list[str] = []
        self.setWindowTitle(self.tr("Plugin Manager"))
        self.resize(720, 460)
        layout = QVBoxLayout(self)
        install_help = QLabel(self.tr(
            "Install your own plugin: choose either the folder containing its "
            ".curvemole-plugin.json manifest or a parent folder containing multiple plugins, "
            "then select it below and choose Review and trust. "
            "This installs it locally; it does not upload it to GitHub."
        ))
        install_help.setWordWrap(True)
        layout.addWidget(install_help)
        community = QHBoxLayout()
        controller = getattr(parent, "plugin_update_controller", None)
        if controller is not None:
            def browse_validated():
                controller.browse(directory=self.directory.text())
                self.scan()

            browse_online = QPushButton(self.tr("Browse validated plugins…"))
            browse_online.clicked.connect(browse_validated)
            community.addWidget(browse_online)
            updates = QPushButton(self.tr("Plugin updates…"))
            updates.clicked.connect(controller.open)
            community.addWidget(updates)
        share = QPushButton(self.tr("Share my plugin on GitHub…"))
        share.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            "https://github.com/SebRoLENS/curvemole/tree/main/custom_plugins#submit-a-plugin"
        )))
        community.addWidget(share)
        layout.addLayout(community)
        explanation = QLabel(
            self.tr(
                "Python plugins can execute arbitrary code. CurveMole reads local JSON metadata first "
                "and loads code only after your explicit approval. Each plugin has its own symbol; hover for its name."
            )
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        row = QHBoxLayout()
        self.directory = QLineEdit(str(directory or ""))
        browse = QPushButton(self.tr("Choose plugin folder…"))
        browse.clicked.connect(self._browse)
        scan = QPushButton(self.tr("Scan"))
        scan.clicked.connect(self.scan)
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        row.addWidget(scan)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_details)
        layout.addWidget(self.list, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        layout.addWidget(self.details)
        buttons_row = QHBoxLayout()
        load = QPushButton(self.tr("Review and trust selected plugin…"))
        load.clicked.connect(self._load)
        close = QPushButton(self.tr("Close"))
        close.clicked.connect(self.accept)
        buttons_row.addWidget(load)
        disable = QPushButton(self.tr("Disable"))
        disable.clicked.connect(lambda: self._remove(False))
        remove = QPushButton(self.tr("Remove"))
        remove.clicked.connect(lambda: self._remove(True))
        buttons_row.addWidget(disable)
        buttons_row.addWidget(remove)
        buttons_row.addStretch(1)
        buttons_row.addWidget(close)
        layout.addLayout(buttons_row)
        self.scan()

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, self.tr("Plugin folder"), self.directory.text()
        )
        if selected:
            self.directory.setText(selected)
            self.scan()

    def scan(self) -> None:
        self.candidates = self.manager.discover_candidates(self.directory.text())
        self.list.clear()
        for candidate in self.candidates:
            self.list.addItem(
                f"{self.manager.symbol(candidate.metadata.identifier)} {candidate.metadata.identifier}  {candidate.metadata.version}  "
                + ("[loaded]" if candidate.metadata.identifier in self.manager.loaded else "[not loaded]")
            )
            self.list.item(self.list.count() - 1).setToolTip(provenance(
                self.manager.symbol(candidate.metadata.identifier),
                candidate.metadata.name or candidate.metadata.identifier, candidate.metadata.identifier))
        if self.candidates:
            self.list.setCurrentRow(0)
        else:
            self.details.setPlainText(self.tr("No plugin manifests or entry points found."))

    def _show_details(self, row: int) -> None:
        if not 0 <= row < len(self.candidates):
            return
        value = self.candidates[row].metadata
        self.details.setPlainText(
            f"Identifier: {value.identifier}\nVersion: {value.version}\n"
            f"API compatibility: {value.api_compatibility}\nLicence: {value.licence}\n"
            f"Capabilities: {', '.join(value.capabilities)}\nSource: {value.source}\n"
            + str(self.manager.installed.get(value.identifier, {}).get("error", ""))
        )

    def _remove(self, forget: bool) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self.candidates):
            return
        identifier = self.candidates[row].metadata.identifier
        parent = self.parent()
        functions = {key for key, owner in self.manager.function_owners.items() if owner == identifier}
        if parent is not None and any(component.function_id in functions
                for model in parent.project.models.values() for component in model.components):
            QMessageBox.warning(self, "Plugin in use", "Remove this plugin's functions from the project first.")
            return
        if forget:
            self.manager.remove(identifier)
        else:
            self.manager.disable(identifier)
        if parent is not None and hasattr(parent, "plugin_host"):
            for key, dialog in list(parent.plugin_host.dialogs.items()):
                if key.startswith(identifier + ":"):
                    try:
                        dialog.close()
                    except RuntimeError:
                        parent._log("Plugin panel was already closed.")
                    del parent.plugin_host.dialogs[key]
        self.scan()

    def _load(self) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self.candidates):
            return
        candidate = self.candidates[row]
        answer = QMessageBox.warning(
            self,
            self.tr("Trust Python plugin"),
            self.tr("Loading executes Python code with your user permissions. Review this source first:")
            + f"\n\n{candidate.metadata.source}\n\n"
            + self.tr("Trust and execute this plugin now?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            metadata = self.manager.load(candidate, trust=True)
            self.loaded_identifiers.append(metadata.identifier)
            self.scan()
            QMessageBox.information(
                self, self.tr("Plugin Manager"), self.tr("Plugin loaded: ") + metadata.identifier
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Plugin Manager"), str(exc))
