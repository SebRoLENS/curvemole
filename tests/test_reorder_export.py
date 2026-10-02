from __future__ import annotations

import csv

import numpy as np
import pandas as pd
import pytest

from curvemole import Component, Curve, Project
from curvemole.core.data import CurveState
from curvemole.core.export import BundleExportSelection, export_bundle, export_function_parameters
from curvemole.core.models import Model
from curvemole.core.registry import default_registry
from curvemole.core.reorder import reorder_component_names
from curvemole.core.serialization import load_project, save_project
from curvemole.core.spectrum_export import export_spectra


@pytest.mark.parametrize("operator", ["multiply", "divide", "convolve"])
def test_reordered_exports_follow_display_names_and_keep_numeric_fit(tmp_path, operator):
    x = np.linspace(-3, 3, 61)
    functions = [
        Component.create("gaussian", name=f"Gaussian{index}",
                         initial={"center": center, "sigma": 1.2, "area": index},
                         operator=operator if index == 2 else "add")
        for index, center in enumerate((2, 0, 1), 1)
    ]
    for component in functions:
        component.parameters["center"].standard_error = .01
    model = Model(components=functions)
    total, arrays = model.evaluate(x, components=True)
    curve = Curve("spectrum", x, total, source="spectrum.csv")
    curve.state = CurveState.FITTED
    project = Project("reordered export")
    project.add_curve(curve)
    project.models[curve.id] = model
    parameter_states = {path: parameter.to_dict() for path, parameter in project.parameter_map().items()}

    reorder_component_names(model, default_registry(), {})
    expected_ids = [functions[index].id for index in (1, 2, 0)]
    expected_names = ["Gaussian1", "Gaussian2", "Gaussian3"]
    assert [item.id for item in model.display_components] == expected_ids
    assert [item.name for item in functions] == ["Gaussian3", "Gaussian1", "Gaussian2"]

    # Persistence must retain presentation order without rewriting composition.
    project = load_project(save_project(project, tmp_path / "ordered.fitproj"))
    model = project.model_for(curve.id)
    before_export = model.to_dict()
    root = tmp_path / "bundle"
    export_bundle(project, root, selection=BundleExportSelection(wide_tables=True, tidy_table=True))

    results = pd.read_csv(root / "fit_results.csv")
    assert results["component_id"].drop_duplicates().tolist() == expected_ids
    assert results["component"].drop_duplicates().tolist() == expected_names
    centers = results.loc[results["parameter"] == "center"]
    np.testing.assert_allclose(centers["value"], [0, 1, 2])
    np.testing.assert_allclose(centers["standard_error"], .01)
    wide = pd.read_csv(root / "data" / "spectrum_wide.csv")
    headers = [f"Component | {name} | gaussian" for name in expected_names]
    assert [column for column in wide if column.startswith("Component | ")] == headers
    np.testing.assert_allclose(wide["Total fit"], total)
    for header, component_id in zip(headers, expected_ids, strict=True):
        np.testing.assert_allclose(wide[header], arrays[component_id], atol=1e-15)
    tidy = pd.read_csv(root / "python" / "data_tidy.csv")
    assert tidy.loc[tidy["quantity"] == "component", "component"].drop_duplicates().tolist() == expected_names

    matrix_path = export_function_parameters(project, tmp_path / "parameters.csv")
    with matrix_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert list(dict.fromkeys(rows[0][1:])) == expected_names
    for name, center in zip(expected_names, (0, 1, 2), strict=True):
        column = next(i for i, pair in enumerate(zip(rows[0], rows[1], strict=True))
                      if pair == (name, "center"))
        assert float(rows[2][column]) == center

    spectrum_path = export_spectra(project, tmp_path / "spectra", [curve.id])[0]
    spectrum = pd.read_csv(spectrum_path)
    spectrum_headers = [f"Component_{name}_gaussian" for name in expected_names]
    assert [column for column in spectrum if column.startswith("Component_")] == spectrum_headers
    np.testing.assert_allclose(spectrum["Total_fit"], total)
    for header, component_id in zip(spectrum_headers, expected_ids, strict=True):
        np.testing.assert_allclose(spectrum[header], arrays[component_id], rtol=1e-10, atol=1e-15)

    assert model.to_dict() == before_export
    assert [item.id for item in model.components] == [item.id for item in functions]
    assert {path: parameter.to_dict() for path, parameter in project.parameter_map().items()} == parameter_states
    np.testing.assert_array_equal(model.evaluate(x), total)


def test_export_keeps_reordered_custom_names_and_skips_disabled_traces(tmp_path):
    functions = [Component.create("gaussian", name=name, initial={"center": center})
                 for name, center in (("Right peak", 2), ("Hidden peak", 1), ("Left peak", 0))]
    for component in functions:
        component.metadata["custom_name"] = True
    functions[1].enabled = False
    model = Model(components=functions)
    curve = Curve("custom", np.arange(4.), np.ones(4))
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    reorder_component_names(model, default_registry(), {})
    root = tmp_path / "bundle"
    export_bundle(project, root, selection=BundleExportSelection(wide_tables=True))
    results = pd.read_csv(root / "fit_results.csv")
    assert results["component"].drop_duplicates().tolist() == ["Left peak", "Hidden peak", "Right peak"]
    wide = pd.read_csv(root / "data" / "custom_wide.csv")
    assert [column for column in wide if column.startswith("Component | ")] == [
        "Component | Left peak | gaussian", "Component | Right peak | gaussian"]
