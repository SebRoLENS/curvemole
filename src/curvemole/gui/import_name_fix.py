"""Keep imported data names consistent with their source filenames.

The interactive importer historically left the selected Y-column label as the
Curve name, while other loading paths exposed the filename.  The data tree
should identify imported files consistently regardless of how they entered the
project.
"""

from __future__ import annotations

from pathlib import Path

from curvemole.gui.main_window import MainWindow

_ORIGINAL_IMPORT_DATA = MainWindow.import_data


def _source_name(curve) -> str | None:
    """Return the filename stem used as the visible name for imported data."""
    source = str(getattr(curve, "source", "") or "").strip()
    if not source:
        return None
    name = Path(source).stem.strip()
    return name or None


def _import_data_with_file_names(self: MainWindow, paths: list[str] | None = None) -> None:
    """Rename only newly imported data after the established import flow ends."""
    existing_ids = {curve.id for curve in self.project.curves}
    _ORIGINAL_IMPORT_DATA(self, paths)

    changed = False
    for curve in self.project.curves:
        if curve.id in existing_ids:
            continue
        name = _source_name(curve)
        if name is not None and curve.name != name:
            curve.name = name
            changed = True

    if changed:
        self.refresh_all()


MainWindow.import_data = _import_data_with_file_names
