from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project
from curvemole.gui.spectrum_export_ui import SpectrumExportDialog


def test_spectrum_export_dialog_defaults_to_active_curve_and_all_fit_traces() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("export dialog")
    first = Curve("first", np.asarray([0.0, 1.0]), np.asarray([1.0, 2.0]))
    second = Curve("second", np.asarray([0.0, 1.0]), np.asarray([2.0, 3.0]))
    project.add_curve(first)
    project.add_curve(second)

    dialog = SpectrumExportDialog(project, second.id, "/tmp")

    assert dialog.selected_curve_ids() == [second.id]
    options = dialog.options()
    assert options.subtract_background is False
    assert options.unmasked_only is False
    assert options.include_background is True
    assert options.include_components is True
    assert options.include_total_fit is True
    assert options.include_residual is True

    dialog.spectra.item(0).setCheckState(Qt.CheckState.Checked)
    assert dialog.selected_curve_ids() == [first.id, second.id]

    dialog.close()
    app.processEvents()
