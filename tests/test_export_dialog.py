from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole.gui.dialogs import ExportBundleDialog


def test_export_dialog_defaults_to_complete_bundle() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = ExportBundleDialog()

    selected = dialog.selection().to_dict()
    assert selected["fit_results"] is True
    assert all(selected.values())
    assert dialog.full_samples.isEnabled() is True
    assert dialog.create_subfolder.isChecked()

    dialog.project_copy.setChecked(False)
    assert dialog.full_samples.isEnabled() is False

    dialog.versioned.setChecked(True)
    dialog.overwrite.setChecked(True)
    assert dialog.overwrite.isChecked() is True
    assert dialog.versioned.isChecked() is False

    dialog.close()
    app.processEvents()


def test_bundle_destination_can_create_a_named_folder(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = ExportBundleDialog(project_name="Experiment / 1")
    dialog.directory.setText(str(tmp_path))
    dialog.folder_name.setText("complete-analysis")
    assert dialog.destination() == tmp_path / "complete-analysis"
    dialog.create_subfolder.setChecked(False)
    assert dialog.destination() == tmp_path
    dialog.close()
    app.processEvents()


def test_update_uses_the_remembered_bundle_folder(tmp_path):
    app = QApplication.instance() or QApplication([])
    existing = tmp_path / "previous-bundle"
    dialog = ExportBundleDialog(str(existing))
    assert dialog.create_subfolder.isChecked()
    dialog.overwrite.setChecked(True)
    assert not dialog.create_subfolder.isChecked()
    assert dialog.destination() == existing
    dialog.close()
    app.processEvents()
