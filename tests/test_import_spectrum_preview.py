from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole.core.importers import import_file
from curvemole.gui.dialogs import ImportMappingDialog


def test_preview_full_data_mapping_cache_and_descending_axis(tmp_path):
    app = QApplication.instance() or QApplication([])
    x = np.linspace(5000, 100, 5000)
    y = np.sin(x)
    y[3000] = 100
    path = tmp_path / "data.csv"
    np.savetxt(path, np.column_stack([x, y, 2*y]), delimiter=",", header="x,y,z", comments="")
    dialog = ImportMappingDialog(path)
    preview = dialog.spectrum_preview
    preview.refresh()
    cache = preview.cache
    item = preview.graph.listDataItems()[0]
    px, py = item.getOriginalDataset()
    np.testing.assert_allclose(px, x[::-1])
    assert max(py) == 100  # Far beyond the numeric table's first rows.
    assert item.opts["autoDownsample"]
    assert item.opts["downsampleMethod"] == "peak"
    assert preview.graph.viewRange()[1][1] >= 100
    dialog.y_columns.item(1).setCheckState(Qt.CheckState.Unchecked)
    dialog.y_columns.item(2).setCheckState(Qt.CheckState.Checked)
    preview.refresh()
    assert preview.cache is cache
    px, py = preview.graph.listDataItems()[0].getOriginalDataset()
    expected = import_file(path, dialog.mapping(), dialog.config())[0]
    np.testing.assert_allclose(py, expected.y[::-1])
    dialog.x_column.setCurrentText("z")
    preview.refresh()
    item = preview.graph.listDataItems()[0]
    assert not item.opts["autoDownsample"]  # Nonmonotonic X: same rule as loaded spectra.
    dialog.y_columns.item(2).setCheckState(Qt.CheckState.Unchecked)
    preview.refresh()
    assert not preview.graph.listDataItems()
    dialog.close()
    app.processEvents()


def test_preview_parser_changes_and_invalid_mapping(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "data.txt"
    path.write_text("x;y\n1,5;2,5\n2,5;3,5\n3,5;5,5\n")
    dialog = ImportMappingDialog(path)
    preview = dialog.spectrum_preview
    preview.refresh()
    assert len(preview.graph.listDataItems()) == 1
    first_cache = preview.cache
    dialog.skip_rows.setValue(1)
    dialog.header.setChecked(False)
    preview.refresh()
    assert preview.cache is not first_cache
    assert len(preview.graph.listDataItems()[0].getOriginalDataset()[0]) == 3
    dialog.close()
    app.processEvents()
