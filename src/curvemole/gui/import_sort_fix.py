"""Keep multi-file imports in human/numeric filename order.

Qt/native file dialogs can return selected files in lexical display order.  That
puts names such as ``spectrum.70`` between ``spectrum.7`` and ``spectrum.6``.
CurveMole should instead import a numbered series in natural order regardless
of the order returned by the platform dialog.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    preview_columns = {}
    if paths is None:
        # Show every file by default: the importer validates the actual table
        # contents rather than assuming the filename extension defines the format.
        if not self._ensure_editable():
            return
        from curvemole.gui.import_file_picker import choose_import_files
        paths, preview_columns = choose_import_files(self)
        if not paths:
            return

    existing_ids = {curve.id for curve in self.project.curves}
    _ORIGINAL_IMPORT_DATA(self, sort_import_paths(list(paths)), preview_columns=preview_columns)

    # The core importer owns imported-data names.  MainWindow still contains a
    # legacy multi-file prefix from before that rule was centralised, so discard
    # only that GUI-side mutation and keep the importer's source-file stem.
    changed = False
    for curve in self.project.curves:
        if curve.id in existing_ids or not curve.source:
            continue
        imported_name = Path(curve.source).stem
        if curve.name != imported_name:
            curve.name = imported_name
            changed = True
    if changed:
        self.refresh_all()


MainWindow.import_data = _import_data_natural_order
