from types import SimpleNamespace

import numpy as np
import pytest

from curvemole import Curve, Project
from curvemole.core.data import Transformation
from curvemole.core.extensions import Contribution, extensions
from curvemole.gui.plugin_services import PluginServices


class DoNotCopy:
    def __deepcopy__(self, memo):
        raise AssertionError("Unrelated spectra or fit results must not be copied")


@pytest.fixture
def services(monkeypatch):
    project = Project("Large project")
    curves = [Curve(str(i), np.arange(100.), np.arange(100.)) for i in range(100)]
    for curve in curves:
        project.add_curve(curve)
    project.results["large_fit"] = DoNotCopy()
    project.fit_history.append({"large_history": DoNotCopy()})
    project.custom_functions.append({"unrelated": DoNotCopy()})
    for curve in curves[2:]:
        curve.metadata["unrelated"] = DoNotCopy()
    owner = "test.spectrum_preview"
    monkeypatch.setattr(extensions, "entries", {
        owner + ":panel": Contribution(owner, owner + ":panel", "Preview", "panels", lambda ctx: None)
    })
    window = SimpleNamespace(
        project=project, active_curve_id=curves[0].id,
        curve_tree=SimpleNamespace(selected_curve_ids=lambda: [c.id for c in curves[:2]]),
        plugin_manager=SimpleNamespace(errors={}),
    )
    return PluginServices(SimpleNamespace(window=window), owner), window, curves


def test_active_state_does_not_copy_project_and_tracks_changes(services):
    service, window, curves = services
    state = service.active_spectrum_state()
    assert state == (window.project.id, curves[0].id, curves[0].content_hash, curves[0].name)
    curves[0].apply_transformation(Transformation("y_add", parameters={"value": 5}))
    assert service.active_spectrum_state()[2] != state[2]
    curves[0].add_mask("mask").excluded[20] = True
    assert service.active_spectrum_state()[2] == curves[0].content_hash
    window.active_curve_id = None
    assert service.active_spectrum_state() == (window.project.id, None, None, None)


@pytest.mark.parametrize("include_selected", [False, True])
def test_spectrum_snapshot_copies_only_requested_data_and_is_detached(services, include_selected):
    service, window, curves = services
    snapshot = service.spectrum_snapshot(include_selected=include_selected)
    assert [c.id for c in snapshot.project.curves] == [c.id for c in curves[:2 if include_selected else 1]]
    assert snapshot.project.id == window.project.id
    assert snapshot.project.models == {}
    assert snapshot.project.results == {}
    snapshot.project.curves[0].apply_transformation(
        Transformation("y_add", parameters={"value": 123})
    )
    snapshot.project.curves[0].metadata["new"] = True
    assert curves[0].y[0] == 0
    assert "new" not in curves[0].metadata


def test_active_model_snapshot_omits_history_results_and_unrelated_settings(services):
    from curvemole.core.models import Component

    service, window, curves = services
    window.project.add_component(curves[0].id, Component.create("gaussian"))
    window.project.add_component(curves[1].id, Component.create("gaussian"))
    first = window.project.models[curves[0].id].components[0]
    second = window.project.models[curves[1].id].components[0]
    parameter = first.parameters["center"]
    other_path = window.project.models[curves[1].id].parameter_path(curves[1].id, second.id, "center")
    parameter.link = f"${{{other_path}}}"
    parameter.link_scope = "absolute"
    second.parameters["center"].value = 123
    window.project.ui_state["plugin_data"] = {
        service.owner: {"temperature": 296}, "other": DoNotCopy()
    }

    snapshot = service.active_model_snapshot()
    assert [curve.id for curve in snapshot.project.curves] == [curves[0].id]
    assert len(snapshot.project.models) == len(window.project.models)
    assert snapshot.project.results == {}
    assert len(snapshot.project.fit_history) == 0
    own_path = snapshot.project.models[curves[0].id].parameter_path(curves[0].id, first.id, "center")
    assert snapshot.project.resolved_parameter_values()[own_path] == 123
    assert snapshot.project.ui_state["plugin_data"] == {service.owner: {"temperature": 296}}
    snapshot.data["temperature"] = 400
    assert service.settings()["temperature"] == 296
