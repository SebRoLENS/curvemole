"""Keep multi-file imports in human/numeric filename order.

Qt/native file dialogs can return selected files in lexical display order.  That
puts names such as ``spectrum.70`` between ``spectrum.7`` and ``spectrum.6``.
CurveMole should instead import a numbered series in natural order regardless
of the order returned by the platform dialog.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from curvemole.gui.main_window import MainWindow

_ORIGINAL_IMPORT_DATA = MainWindow.import_data
_NUMBER_TOKEN = re.compile(r"(\d+)")


def natural_import_sort_key(path: str) -> tuple[tuple[tuple[int, object], ...], str]:
    """Return a deterministic natural-sort key for a path's filename."""
    name = Path(path).name.casefold()
    parts: list[tuple[int, object]] = []
    for token in _NUMBER_TOKEN.split(name):
        if not token:
            continue
        if token.isdigit():
            parts.append((1, int(token)))
        else:
            parts.append((0, token))
    return tuple(parts), name


def sort_import_paths(paths: list[str]) -> list[str]:
    """Sort selected data files naturally by filename, preserving full paths."""
    return sorted(paths, key=natural_import_sort_key)


def _import_data_natural_order(self: MainWindow, paths: list[str] | None = None) -> None:
    if paths is None:
        # Preserve the existing user-facing import dialog, then normalise the
        # platform-dependent selection order before handing it to the original
        # importer.  The original method still performs all validation/mapping.
        if not self._ensure_editable():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("Import one-dimensional curves"),
            "",
            self.tr("Supported data (*.txt *.dat *.csv *.tsv);;All files (*)"),
        )
        if not paths:
            return

    _ORIGINAL_IMPORT_DATA(self, sort_import_paths(list(paths)))


MainWindow.import_data = _import_data_natural_order
