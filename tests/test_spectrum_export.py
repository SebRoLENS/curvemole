from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from curvemole import Component, Curve, Project
from curvemole.core.spectrum_export import (
    SpectrumExportOptions,
    export_spectra,
    spectrum_export_dataframe,
    spectrum_export_filename,
)


def _project_with_background() -> tuple[Project, Curve]:
    x = np.asarray([0.0, 1.0, 2.0, 3.0])
    y = np.asarray([10.0, 11.0, 12.0, 13.0])
    curve = Curve(
        "sample A",
        x,
        y,
        x_label="Wavenumber",
        x_unit="cm-1",
        y_label="Intensity",
        source="/data/original.xy",
        metadata={"import": {"file_name": "original.xy", "delimiter": "whitespace"}},
    )
    project = Project("spectrum export")
    project.add_curve(curve)
    background = Component.create("constant", initial={"offset": 1.0})
    background.name = "Baseline1"
    background.is_background = True
    signal = Component.create("constant", initial={"offset": 2.0})
    signal.name = "Signal1"
    project.model_for(curve.id).add(background)
    project.model_for(curve.id).add(signal)
    return project, curve


def test_dataframe_can_subtract_background_and_drop_masked_rows() -> None:
    project, curve = _project_with_background()
    curve.masks[curve.active_mask].excluded[1] = True

    frame = spectrum_export_dataframe(
        project,
        curve.id,
        options=SpectrumExportOptions(subtract_background=True, unmasked_only=True),
    )

    assert len(frame) == 3
    assert list(frame.columns) == [
        "Wavenumber [cm-1]",
        "Spectrum | Intensity - background",
        "Background",
        "Component | Baseline1 | constant | background",
        "Component | Signal1 | constant",
        "Total fit - background",
        "Residual (data - fit)",
    ]
    assert frame["Wavenumber [cm-1]"].tolist() == [0.0, 2.0, 3.0]
    assert frame["Spectrum | Intensity - background"].tolist() == [9.0, 11.0, 12.0]
    assert frame["Background"].tolist() == [1.0, 1.0, 1.0]
    assert frame["Total fit - background"].tolist() == [2.0, 2.0, 2.0]
    assert frame["Residual (data - fit)"].tolist() == [7.0, 9.0, 10.0]


def test_export_preserves_original_extension_and_writes_replottable_columns(tmp_path: Path) -> None:
    project, curve = _project_with_background()

    created = export_spectra(project, tmp_path, [curve.id])

    assert [path.name for path in created] == ["sample A_curvemole.xy"]
    assert spectrum_export_filename(curve) == "sample A_curvemole.xy"
    frame = pd.read_csv(created[0], sep="\t")
    assert frame.columns[0] == "Wavenumber [cm-1]"
    assert "Spectrum | Intensity" in frame.columns
    assert "Total fit" in frame.columns
    assert "Residual (data - fit)" in frame.columns
    assert "Component | Signal1 | constant" in frame.columns


def test_unknown_source_extension_is_preserved(tmp_path: Path) -> None:
    curve = Curve(
        "vendor spectrum",
        np.asarray([0.0, 1.0]),
        np.asarray([2.0, 3.0]),
        source="/tmp/acquisition.vendorformat",
    )
    project = Project("unknown extension")
    project.add_curve(curve)

    created = export_spectra(project, tmp_path, [curve.id])

    assert created[0].suffix == ".vendorformat"
    assert created[0].name == "vendor spectrum_curvemole.vendorformat"
