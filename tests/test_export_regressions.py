"""Regression tests for export (formerly grouped by audit)."""
from __future__ import annotations

import numpy as np
import pytest

from curvemole import Component, Curve, Project, Series
from curvemole.core.errors import (
    CurveMoleError,
)
from curvemole.core.export import (
    BundleExportSelection,
    export_bundle,
    tidy_dataframe,
    wide_dataframe,
)
from curvemole.core.functions import FunctionDefinition
from curvemole.core.registry import default_registry
from curvemole.core.spectrum_export import (
    export_spectra,
    spectrum_export_dataframe,
    spectrum_export_filename,
)


def test_failed_bundle_regeneration_leaves_all_preexisting_files_untouched(tmp_path, monkeypatch):
    project = Project()
    curve = Curve("data", [0, 1], [0, 1])
    project.add_series(Series("series", [curve]))
    selection = BundleExportSelection.none(wide_tables=True, html_summary=True)
    export_bundle(project, tmp_path, selection=selection)
    before = {file.relative_to(tmp_path): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    config = dict(project.export_config)
    curve.move_points([1], y=[9])

    def fail(*args, **kwargs):
        raise OSError("Synthetic write failure")

    monkeypatch.setattr("curvemole.core.export.bundle.generate_html_report", fail)
    with pytest.raises(OSError, match="Synthetic write failure"):
        export_bundle(project, tmp_path, selection=selection, overwrite=True)
    assert {file.relative_to(tmp_path): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()} == before
    assert project.export_config == config

def test_export_refuses_existing_files_and_links_before_writing_anything(tmp_path):
    p = Project()
    a = Curve("a", [0, 1], [1, 2])
    b = Curve("b", [0, 1], [3, 4])
    p.add_series(Series("s", [a, b]))
    dest = tmp_path / spectrum_export_filename(b)
    dest.write_text("keep this")
    with pytest.raises(FileExistsError):
        export_spectra(p, tmp_path, [a.id, b.id])
    assert not (tmp_path / spectrum_export_filename(a)).exists()
    assert dest.read_text() == "keep this"
    external = tmp_path / "outside.txt"
    external.write_text("external")
    dest.unlink()
    dest.symlink_to(external)
    with pytest.raises(CurveMoleError, match="symbolic"):
        export_spectra(p, tmp_path, [b.id], overwrite=True)
    assert external.read_text() == "external"

def test_export_preserves_float64_values_and_cleans_staging_files(tmp_path):
    p = Project()
    c = Curve("precision", [0, 1], [1.0000000000001, 1.0000000000002])
    p.add_curve(c)
    dest = export_spectra(p, tmp_path, [c.id])[0]
    assert np.loadtxt(dest, skiprows=1)[:, 1] == pytest.approx(c.y, rel=0, abs=0)
    assert list(tmp_path.glob(".curvemole-export-*")) == []
    dest.write_text("old")
    export_spectra(p, tmp_path, [c.id], overwrite=True)
    assert dest.read_text() != "old"

def test_export_works_on_a_filesystem_without_hardlinks(tmp_path, monkeypatch):
    import errno

    def unsupported(*args):
        raise OSError(errno.ENOTSUP, "no hard links")

    monkeypatch.setattr("curvemole.core.spectrum_export.os.link", unsupported)
    p = Project()
    c = Curve("fat", [0, 1], [2, 3])
    p.add_curve(c)
    path = export_spectra(p, tmp_path, [c.id])[0]
    assert path.exists()
    with pytest.raises(FileExistsError):
        export_spectra(p, tmp_path, [c.id])

def test_export_registry_does_not_modify_default_functions():
    from curvemole.core.export import _registry_for_project

    p = Project(custom_functions=[{"identifier": "audit_export_local", "formula": "2*x"}])
    scoped = _registry_for_project(p)
    assert "audit_export_local" in scoped.identifiers()
    assert "audit_export_local" not in default_registry().identifiers()

def test_export_evaluates_only_requested_model_quantities(monkeypatch, tmp_path):
    from curvemole.core.export import ExportSelection, wide_dataframe
    from curvemole.core.spectrum_export import SpectrumExportOptions, export_spectra
    project = Project('export calls')
    for i in range(3):
        curve = Curve(str(i), np.arange(5.), np.ones(5))
        project.add_curve(curve)
        background = Component.create('constant')
        background.is_background = True
        factor = Component.create('constant', operator='multiply')
        project.model_for(curve.id).components = [background, factor]
    calls = []
    original = FunctionDefinition.evaluate
    def evaluate(self, *args, **kwargs):
        calls.append(self.identifier)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(FunctionDefinition, 'evaluate', evaluate)
    curve = project.curves[0]
    model = project.models[curve.id]
    wide_dataframe(curve, model, selection=ExportSelection(total_fit=False, residual=False, background=False, components=False))
    assert calls == []
    wide_dataframe(curve, model)
    assert len(calls) == 2
    resolutions = []
    original_resolve = Project.resolved_parameter_values
    def resolve(self):
        resolutions.append(1)
        return original_resolve(self)
    monkeypatch.setattr(Project, 'resolved_parameter_values', resolve)
    export_spectra(project, tmp_path, [c.id for c in project.curves], options=SpectrumExportOptions())
    assert len(resolutions) == 1

@pytest.mark.parametrize('quick', [False, True])
def test_export_keeps_axis_data_and_error_columns_with_colliding_headers(quick):
    c = Curve('collision', [10, 20], [1, 2], x_label='Spectrum_y' if quick else 'sigma_y',
              y_label='y' if quick else 'sigma_y', sigma_y=[.1, .2])
    p = Project()
    p.add_curve(c)
    frame = spectrum_export_dataframe(p, c.id) if quick else wide_dataframe(c)
    roles = frame.attrs['column_roles']
    assert frame.columns.is_unique
    assert frame[roles['x']].to_numpy() == pytest.approx([10, 20])
    assert frame[roles['y']].to_numpy() == pytest.approx([1, 2])
    assert any(np.array_equal(frame[name].to_numpy(), [.1, .2]) for name in frame)
    if not quick:
        tidy = tidy_dataframe(p)
        y = tidy[tidy['quantity'] == roles['y']]
        assert y['x'].to_numpy() == pytest.approx([10, 20])
        assert y['value'].to_numpy() == pytest.approx([1, 2])

@pytest.mark.parametrize('inverse', [True, False])
def test_quick_export_writes_weights_and_their_semantics(tmp_path, inverse):
    import pandas as pd
    p = Project()
    c = Curve('weighted', [0, 1, 2], [1, 2, 3], weights=[1, 2, 3],
              weights_are_inverse_variance=inverse)
    p.add_curve(c)
    [path] = export_spectra(p, tmp_path, [c.id])
    frame = pd.read_csv(path, sep='\t')
    assert frame['weight'].to_numpy() == pytest.approx([1, 2, 3])
    assert (frame['weights_are_inverse_variance'] == int(inverse)).all()
