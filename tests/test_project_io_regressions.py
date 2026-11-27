"""Regression tests for project io (formerly grouped by audit)."""
from __future__ import annotations

import copy
import io
import json
import zipfile

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model, Project, Transformation
from curvemole.core.archive_validation import ArchiveLimits
from curvemole.core.errors import (
    FitError,
    ProjectFormatError,
)
from curvemole.core.fitting import (
    FitPlan,
    FitSettings,
)
from curvemole.core.importers import ColumnMapping, import_file
from curvemole.core.matrices import BlockDiagonalMatrix
from curvemole.core.recovery import RecoveryManager
from curvemole.core.serialization import load_project, save_project, validate_project_archive
from curvemole.core.workflow import dump_workflow, run_workflow


def link_to(project, target, source):
    src = project.model_for(source.id).components[0]
    dst = project.model_for(target.id).components[0]
    dst.parameters["offset"].link = f"${{{source.id}.{src.id}.offset}}"


@pytest.mark.parametrize("names", [("first", "second"), ("same", "same")])
def test_workflow_round_trip_remaps_repeated_local_and_external_references(tmp_path, names):
    path = tmp_path / "data.csv"
    path.write_text("x,y\n0,1\n1,2\n2,3\n")
    project = Project()
    for name in names:
        curve = import_file(path, ColumnMapping(x=0, y=[1]))[0]
        curve.name = name
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create("constant", initial={"offset": 2.}))
    a, b = project.curves
    first = project.model_for(a.id).components[0]
    local = Component.create("constant")
    local.parameters["offset"].link = f"${{{a.id}.{first.id}.offset}} + ${{{a.id}.{first.id}.offset}}"
    local.parameters["offset"].link_reference_scopes = ["relative", "absolute"]
    project.model_for(a.id).add(local)
    link_to(project, b, a)
    project.model_for(b.id).components[0].parameters["offset"].link_scope = "absolute"
    workflow = dump_workflow(project, tmp_path / "workflow.yml")
    restored = run_workflow(workflow).project
    assert set(project.resolved_parameter_values().values()) == set(restored.resolved_parameter_values().values())
    for original, loaded in zip(project.curves, restored.curves, strict=True):
        assert original.id != loaded.id
        np.testing.assert_allclose(
            project.model_for(original.id).evaluate(original.x, curve_id=original.id, values=project.resolved_parameter_values()),
            restored.model_for(loaded.id).evaluate(loaded.x, curve_id=loaded.id, values=restored.resolved_parameter_values()))
    assert restored.model_for(restored.curves[0].id).component(local.id).parameters["offset"].link_reference_scopes == ["relative", "absolute"]
    # The exported identities also resolve the explicit global fit selection.
    import yaml
    payload = yaml.safe_load(workflow.read_text())
    payload["fit"] = {"mode": "global", "curves": [curve.id for curve in project.curves]}
    workflow.write_text(yaml.safe_dump(payload))
    fitted = run_workflow(workflow)
    assert fitted.result.success
    assert set(fitted.result.curve_outputs) == {curve.id for curve in fitted.project.curves}

def test_validator_rejects_malformed_schema_and_load_wraps_errors(tmp_path):
    path = tmp_path / "bad.fitproj"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": 3, "project": []}))
    assert validate_project_archive(path, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(path)

def test_archive_resource_limits_are_checked_before_loading_arrays(tmp_path):
    p = Project()
    p.add_curve(Curve("c", np.arange(20.0), np.arange(20.0)))
    path = save_project(p, tmp_path / "budget.fitproj")
    with pytest.raises(ProjectFormatError, match="budget"):
        load_project(path, limits=ArchiveLimits(expanded_bytes=10))
    with pytest.raises(ProjectFormatError, match="array-size"):
        load_project(path, limits=ArchiveLimits(array_bytes=8))
    assert validate_project_archive(path) == []

def test_forged_array_shape_is_rejected_without_allocating_claimed_memory(tmp_path):
    payload = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        payload, {"descr": "<f8", "fortran_order": False, "shape": (10**12,)}
    )
    path = tmp_path / "forged.fitproj"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": 3, "project": {"id": "p"}}))
        archive.writestr("giant.npy", payload.getvalue())
    with pytest.raises(ProjectFormatError, match="array-size"):
        load_project(path)

@pytest.mark.parametrize(
    "section,value",
    [("models", {"components": [None]}), ("masks", [{}]), ("transformations", [{}])],
)
def test_validator_catches_invalid_nested_records(tmp_path, section, value):
    p = Project()
    c = Curve("bad metadata", [0, 1], [2, 3])
    p.add_curve(c)
    path = save_project(p, tmp_path / "nested.fitproj")
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    if section == "models":
        manifest["project"]["models"][c.id] = value
    else:
        manifest["project"]["curves"][c.id][section] = value
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in contents.items():
            archive.writestr(name, payload)
    assert validate_project_archive(path, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(path)

@pytest.mark.parametrize('delimiter', [',', ';', '\t'])
def test_workflow_roundtrip_retains_import_mapping(tmp_path, delimiter):
    source = tmp_path / 'input data.txt'
    source.write_text('\n'.join(delimiter.join(row) for row in [('x','a','b'), ('0','2','3'), ('1','4','5'), ('2','6','7')]))
    project = Project('import roundtrip')
    for index, curve in enumerate(import_file(source, ColumnMapping(x=0, y=[1, 2]))):
        curve.name = f'curve {index}'
        project.add_curve(curve)
    restored = run_workflow(dump_workflow(project, tmp_path / 'workflow.yaml')).project
    for original, replay in zip(project.curves, restored.curves, strict=True):
        np.testing.assert_array_equal(original.x, replay.x)
        np.testing.assert_array_equal(original.y, replay.y)

def test_independent_covariance_stays_blocked_in_archive(tmp_path):
    project = Project('independent')
    for i in range(5):
        curve = Curve(str(i), np.arange(12.), np.arange(12.) * (i + 1) + .01)
        project.add_curve(curve)
        project.model_for(curve.id).add(Component.create('linear'))
    result = Fitter().fit(FitPlan([c.id for c in project.curves]), project.curves, project.models)
    assert isinstance(result.covariance, BlockDiagonalMatrix)
    assert sum(b.size for b in result.covariance.blocks) == 5 * 4
    np.testing.assert_array_equal(result.covariance.submatrix([0, 3])[0, 1], 0)
    project.results['last_fit'] = result
    restored = load_project(save_project(project, tmp_path / 'blocks.fitproj')).results['last_fit']
    assert isinstance(restored.covariance, BlockDiagonalMatrix)
    np.testing.assert_allclose(np.asarray(restored.covariance), np.asarray(result.covariance))

def test_checked_replay_restores_initial_de_state_after_archive(tmp_path):
    x = np.linspace(-5, 5, 51)
    curve = Curve('replay', x, np.exp(-.5*((x-.4)/.8)**2), sigma_y=np.full(len(x), .01))
    model = Model(components=[Component.create('gaussian', initial={'area': 2.5, 'center': 0, 'sigma': 1})])
    plan = FitPlan([curve.id], settings=FitSettings(solver='differential_evolution', seed=1729, de_maxiter=20))
    baseline = Fitter().fit(plan, [curve], {curve.id: model})
    project = Project()
    project.add_curve(curve)
    project.models[curve.id] = model
    project.results['last_fit'] = baseline
    loaded = load_project(save_project(project, tmp_path/'replay.fitproj'))
    saved = loaded.results['last_fit']
    replay = Fitter().replay(saved, loaded.curves)
    assert replay.provenance['executions'] == saved.provenance['executions']
    assert [p.value for p in replay.parameters.values()] == [p.value for p in saved.parameters.values()]
    changed = copy.deepcopy(saved)
    changed.provenance['environment']['numpy'] = 'different'
    with pytest.raises(FitError, match='environment changed'):
        Fitter().replay(changed, loaded.curves)
    changed = copy.deepcopy(saved)
    changed.provenance['functions']['gaussian']['sha256'] = 'different'
    with pytest.raises(FitError, match='definitions changed'):
        Fitter().replay(changed, loaded.curves)
    loaded.curves[0].apply_transformation(Transformation('y_multiply', {'value': 2}))
    with pytest.raises(FitError, match='input data changed'):
        Fitter().replay(saved, loaded.curves)

@pytest.mark.parametrize('invalid', [{'minimum': 5}, {'link': 'invalid('}])
def test_invalid_constraints_are_reported_and_do_not_hide_valid_recoveries(tmp_path, invalid):
    p = Project()
    c = Curve('curve', [0, 1, 2], [1, 2, 3])
    p.add_curve(c)
    p.add_component(c.id, Component.create('constant'))
    good = save_project(p, tmp_path / 'good.recovery-1.fitproj')
    bad = tmp_path / 'bad.recovery-2.fitproj'
    with zipfile.ZipFile(good) as z:
        payload = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(payload['manifest.json'])
    parameter = manifest['project']['models'][c.id]['components'][0]['parameters']['offset']
    parameter.update(invalid)
    payload['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(bad, 'w') as z:
        for name, value in payload.items():
            z.writestr(name, value)
    assert validate_project_archive(bad, raise_on_error=False)
    with pytest.raises(ProjectFormatError):
        load_project(bad)
    assert RecoveryManager(tmp_path).candidates() == [good]
