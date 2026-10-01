from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project, Series
from curvemole.gui.series_groups import SourceSpectrumComboBox


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project():
    project = Project()
    for series_name, curve_names in (
        ("Pressure scan", ("Spectrum 20", "Spectrum 2")),
        ("Calibration", ("Spectrum 2", "Reference")),
    ):
        curves = [Curve(name, [0., 1.], [1., 2.]) for name in curve_names]
        project.add_series(Series(series_name, curves))
    return project


def test_spectrum_selector_preserves_series_and_spectrum_order(app):
    project = _project()
    combo = SourceSpectrumComboBox(project, project.curves[0].id)
    assert [combo.itemText(row) for row in range(combo.count())] == [
        "Same spectrum as this parameter",
        "",
        "Specific spectrum (fixed when copied)",
        "Pressure scan",
        "    Spectrum 20",
        "    Spectrum 2",
        "Calibration",
        "    Spectrum 2",
        "    Reference",
    ]
    assert [combo.itemData(row) for row in range(combo.count()) if combo.itemData(row) not in (None, "self")] == [
        curve.id for curve in project.curves
    ]
    combo.close()


def test_spectrum_selector_headings_are_not_selectable_and_share_series_style(app):
    project = _project()
    combo = SourceSpectrumComboBox(project, project.curves[0].id)
    for row in (1, 2, 3, 6):
        assert not combo.model().item(row).flags() & Qt.ItemFlag.ItemIsSelectable
        assert combo.itemData(row) is None
    for row in (2, 3, 6):
        assert combo.model().item(row).font().bold()
    for row in (0, 4, 5, 7, 8):
        assert combo.model().item(row).flags() & Qt.ItemFlag.ItemIsSelectable
    assert combo.view().alternatingRowColors()
    assert combo.view().spacing() == 3
    combo.close()


def test_spectrum_selector_distinguishes_relative_and_fixed_current_spectrum(app):
    project = _project()
    target = project.curves[2]
    combo = SourceSpectrumComboBox(project, target.id)
    assert combo.currentData() == "self"
    assert target.name in combo.itemData(0, Qt.ItemDataRole.ToolTipRole)
    assert "destination spectrum" in combo.itemData(0, Qt.ItemDataRole.ToolTipRole)
    fixed_index = combo.findData(target.id)
    combo.setCurrentIndex(fixed_index)
    assert combo.currentData() == target.id
    assert combo.itemData(fixed_index, Qt.ItemDataRole.ToolTipRole) == (
        "Calibration / Spectrum 2; keeps this spectrum when copied."
    )
    combo.setCurrentIndex(combo.findData("self"))
    assert combo.currentData() == "self"
    combo.close()
