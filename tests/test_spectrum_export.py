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
    background.name = "Baseline 1"
    background.is_background = True
    signal = Component.create("constant", initial={"offset": 2.0})
    signal.name = "Signal 1"
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
        "Wavenumber_cm-1",
        "Spectrum_Intensity_background_subtracted",
        "Background",
        "Component_Baseline_1_constant_background",
        "Component_Signal_1_constant",
        "Total_fit_background_subtracted",
        "Residual_data_minus_fit",
    ]
    assert all(not any(char.isspace() for char in column) for column in frame.columns)
    assert frame["Wavenumber_cm-1"].tolist() == [0.0, 2.0, 3.0]
    assert frame["Spectrum_Intensity_background_subtracted"].tolist() == [9.0, 11.0, 12.0]
    assert frame["Background"].tolist() == [1.0, 1.0, 1.0]
    assert frame["Total_fit_background_subtracted"].tolist() == [2.0, 2.0, 2.0]
    assert frame["Residual_data_minus_fit"].tolist() == [7.0, 9.0, 10.0]


def test_export_preserves_original_extension_and_writes_replottable_columns(tmp_path: Path) -> None:
    project, curve = _project_with_background()

    created = export_spectra(project, tmp_path, [curve.id])

    assert [path.name for path in created] == ["sample A_curvemole.xy"]
    assert spectrum_export_filename(curve) == "sample A_curvemole.xy"
    frame = pd.read_csv(created[0], sep="\t")
    assert frame.columns[0] == "Wavenumber_cm-1"
    assert "Spectrum_Intensity" in frame.columns
    assert "Total_fit" in frame.columns
    assert "Residual_data_minus_fit" in frame.columns
    assert "Component_Signal_1_constant" in frame.columns
    assert all(not any(char.isspace() for char in column) for column in frame.columns)


def test_whitespace_in_labels_and_units_is_never_written_to_headers() -> None:
    curve = Curve(
        "raman",
        np.asarray([0.0, 1.0]),
        np.asarray([2.0, 3.0]),
        x_label="Raman shift",
        x_unit="cm -1",
        y_label="Relative intensity",
        y_unit="arb. units",
    )
    project = Project("safe headers")
    project.add_curve(curve)

    frame = spectrum_export_dataframe(project, curve.id)

    assert list(frame.columns) == [
        "Raman_shift_cm_-1",
        "Spectrum_Relative_intensity_arb._units",
    ]
    assert all(not any(char.isspace() for char in column) for column in frame.columns)


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
