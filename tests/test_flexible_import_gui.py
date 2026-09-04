from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole.gui.dialogs import ImportMappingDialog


def test_import_dialog_exposes_detected_leading_rows(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "spectrum.xy"
    path.write_text(
        "Instrument: CurveLab\n"
        "Acquisition: test\n"
        "x y\n"
        "0 1\n"
        "1 2\n",
        encoding="utf-8",
    )

    dialog = ImportMappingDialog(path)

    assert dialog.skip_rows.value() == 2
    assert dialog.config().skip_rows == 2

    dialog.close()
    app.processEvents()
