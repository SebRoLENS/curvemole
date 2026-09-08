from __future__ import annotations

import copy

import pytest

from curvemole import Component, Curve, Project, Series
from curvemole.core.export import BundleExportSelection, export_bundle
from curvemole.core.notebook import LaboratoryNotebook, description_key, export_notebook
from curvemole.core.serialization import load_project, save_project


def annotated_project():
    project = Project("Pressure study")
    curves = [Curve(name, [0., 1., 2.], [1., 2., 3.]) for name in ("Ambient", "5 GPa")]
    series = Series("Sample A", curves)
    project.add_series(series)
    component = Component.create("constant")
    for curve in curves:
        project.add_component(curve.id, copy.deepcopy(component))
    notebook = project.notebook
    notebook.notes = "Preparation at 25 °C\nRepeat tomorrow."
    notebook.set_description(project, "series", series.id, "Hydrostatic loading")
    notebook.set_description(project, "spectrum", curves[0].id, "Before compression")
    notebook.set_description(project, "function", component.id, "Reference background", curves[0].id)
    notebook.set_description(project, "function", component.id, "High-pressure background", curves[1].id)
    return project, series, curves, component


def test_notebook_round_trip_and_old_project_default(tmp_path):
    project, _, _, _ = annotated_project()
    path = save_project(project, tmp_path / "notes.fitproj", portable=True)
    restored = load_project(path)
    assert restored.notebook.to_dict() == project.notebook.to_dict()
    assert LaboratoryNotebook.from_dict({}).notes == ""
    empty = load_project(save_project(Project(), tmp_path / "empty.fitproj"))
    assert not empty.notebook.descriptions


def test_descriptions_follow_identity_moves_renames_deletions_and_restoration(tmp_path):
    project, series, curves, component = annotated_project()
    notes = project.notebook
    series.name = "Renamed sample"
    curves[0].name = "Renamed spectrum"
    project.models[curves[0].id].components[0].name = "Renamed function"
    project.touch()
    key = description_key("function", component.id, curves[0].id)
    entry = notes.descriptions[key]
    assert entry.title == "Renamed sample / Renamed spectrum / Renamed function (constant)"
    assert notes.descriptions[description_key("function", component.id, curves[1].id)].text == "High-pressure background"
    target = Series("Moved")
    project.add_series(target)
    target.add(series.remove(curves[0].id))
    project.touch()
    assert entry.series_name == "Moved"
    model = project.models[curves[0].id]
    project.remove_curve(curves[0].id)
    assert entry.deleted
    assert notes.descriptions[description_key("spectrum", curves[0].id)].deleted
    assert not notes.descriptions[description_key("function", component.id, curves[1].id)].deleted
    project.dataset.series.remove(series)
    project.touch()
    assert notes.descriptions[description_key("series", series.id)].deleted
    restored = load_project(save_project(project, tmp_path / "deleted.fitproj"))
    text = restored.notebook.as_text(restored)
    assert "[DELETED] Renamed sample" in text
    assert "Reference background" in text
    assert "Before compression" in text
    # Undo can restore the original identities without losing or duplicating notes.
    target.add(curves[0])
    project.models[curves[0].id] = model
    project.touch()
    assert not entry.deleted
    assert len(notes.descriptions) == 4


def test_notebook_export_is_selectable_without_fit_and_respects_ownership(tmp_path):
    project, _, _, _ = annotated_project()
    direct = export_notebook(project, tmp_path / "direct.txt")
    selection = BundleExportSelection(fit_results=False, laboratory_notebook=True)
    root = tmp_path / "bundle"
    summary = export_bundle(project, root, selection=selection)
    assert [path.name for path in summary.created] == ["laboratory_notebook.txt"]
    assert direct.read_text(encoding="utf-8") == (root / "laboratory_notebook.txt").read_text(encoding="utf-8")
    assert "Preparation at 25 °C" in direct.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_bundle(project, root, selection=selection)
    project.notebook.notes = "Updated notes"
    export_bundle(project, root, selection=selection, overwrite=True)
    assert "Updated notes" in (root / "laboratory_notebook.txt").read_text(encoding="utf-8")
    # A notebook can also be the only content in an empty project.
    empty = Project()
    empty.notebook.notes = "Planning the experiment"
    export_bundle(empty, tmp_path / "planning", selection=selection)


def test_read_only_description_does_not_mutate_project():
    project, series, _, _ = annotated_project()
    before = project.notebook.to_dict()
    project.read_only = True
    with pytest.raises(PermissionError):
        project.notebook.set_description(project, "series", series.id, "Forbidden")
    assert project.notebook.to_dict() == before
