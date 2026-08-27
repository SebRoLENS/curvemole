from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole.gui.dialogs import ExportBundleDialog


def test_export_dialog_defaults_to_fit_results_only() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = ExportBundleDialog()

    selected = dialog.selection().to_dict()
    assert selected["fit_results"] is True
    assert sum(bool(value) for value in selected.values()) == 1
    assert dialog.full_samples.isEnabled() is False

    dialog.project_copy.setChecked(True)
    assert dialog.full_samples.isEnabled() is True

    dialog.versioned.setChecked(True)
    dialog.overwrite.setChecked(True)
    assert dialog.overwrite.isChecked() is True
    assert dialog.versioned.isChecked() is False

    dialog.close()
    app.processEvents()
