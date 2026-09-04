"""Extension-agnostic data import and configurable leading-row skipping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QLabel, QSpinBox

from curvemole.core.importers import ImportConfig
from curvemole.gui.dialogs import ImportMappingDialog
from curvemole.gui.main_window import MainWindow

_ORIGINAL_DIALOG_INIT = ImportMappingDialog.__init__


def _dialog_init(
    self: ImportMappingDialog,
    path: str | Path,
    *,
    batch_size: int = 1,
    parent: Any | None = None,
) -> None:
    _ORIGINAL_DIALOG_INIT(self, path, batch_size=batch_size, parent=parent)

    parsing_group = self.header.parentWidget()
    self.skip_rows = QSpinBox(parsing_group)
    self.skip_rows.setRange(0, 1_000_000)
    self.skip_rows.setValue(int(self.inspection.config.skip_rows))
    self.skip_rows.setToolTip(
        self.tr(
            "Ignore this many physical lines at the beginning of the file before parsing."
        )
    )
    label = QLabel(self.tr("Ignore first rows:"), parsing_group)
    layout = parsing_group.layout() if parsing_group is not None else None
    if layout is not None and hasattr(layout, "insertWidget"):
        position = max(0, layout.count() - 1)
        layout.insertWidget(position, label)
        layout.insertWidget(position + 1, self.skip_rows)
    self.skip_rows.valueChanged.connect(self._reload)


def _dialog_config(self: ImportMappingDialog) -> ImportConfig:
    skip_rows = (
        self.skip_rows.value()
        if hasattr(self, "skip_rows")
        else int(self.inspection.config.skip_rows)
    )
    return ImportConfig(
        delimiter=self.delimiter.currentData(),
        decimal=self.decimal.currentText(),
        header=self.header.isChecked(),
        skip_rows=skip_rows,
    )


def _content_aware_drop_event(self: MainWindow, event: Any) -> None:
    paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
    projects = [path for path in paths if Path(path).suffix.lower() == ".fitproj"]
    data = [
        path
        for path in paths
        if Path(path).is_file() and Path(path).suffix.lower() != ".fitproj"
    ]
    if projects:
        self.open_project(projects[0])
    elif data:
        self.import_data(data)
    if paths:
        event.acceptProposedAction()


ImportMappingDialog.__init__ = _dialog_init
ImportMappingDialog.config = _dialog_config
MainWindow.dropEvent = _content_aware_drop_event
