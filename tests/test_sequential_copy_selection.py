import copy

import numpy as np
import pytest

from curvemole import Component, Curve, Fitter, Model
from curvemole.core.fitting import FitMode, FitPlan
from curvemole.core.sequential_fit import SequentialFitPlan, _merge_selected_components


def test_existing_functions_are_never_overwritten_or_duplicated_by_identity():
    source = Component.create("gaussian", initial={"center": 1.0})
    existing = Model(components=[copy.deepcopy(source)])
    existing.components[0].parameters["center"].value = 8.0
    extra = Component.create("gaussian", name=source.name)
    existing.add(extra)
    before = copy.deepcopy(existing.to_dict())
    result = _merge_selected_components(Model(components=[source]), existing, {source.id}, "target")
    assert result.to_dict() == before
    assert existing.to_dict() == before


def test_exclude_all_keeps_target_model_unchanged():
    source = Model(components=[Component.create("gaussian")])
    existing = Model(components=[Component.create("linear")])
    result = _merge_selected_components(source, existing, set(), "target")
    assert result.to_dict() == existing.to_dict()


def test_base_fit_plan_remains_supported():
    x = np.linspace(-5, 5, 101)
    curves = [Curve(str(i), x, np.exp(-x*x)) for i in range(2)]
    model = Model(components=[Component.create("gaussian")])
    models = {curves[0].id: model, curves[1].id: Model()}
    plan = FitPlan([c.id for c in curves], FitMode.SEQUENTIAL)
    result = Fitter().fit(plan, curves, models)
    assert curves[1].id in result.curve_outputs


def test_selection_preserves_local_functions_across_steps_and_resume():
    x = np.linspace(-5, 5, 401)
    curves = []
    models = {}
    locals_ = []
    peak = Component.create("gaussian", initial={"area": 3., "center": 0., "sigma": .8})
    for index in range(4):
        y = index + 3 * np.exp(-.5 * ((x - .1 * index) / .8) ** 2) / (.8 * np.sqrt(2 * np.pi))
        curve = Curve(str(index), x, y)
        curves.append(curve)
        local = Component.create("constant", initial={"offset": float(index)})
        local.parameters["offset"].fixed = True
        locals_.append(local)
        models[curve.id] = Model(components=[local])
    models[curves[0].id].add(peak)
    plan = SequentialFitPlan([c.id for c in curves[:3]], FitMode.SEQUENTIAL,
                             excluded_copy_component_ids=(locals_[0].id,),
                             monitor_residuals=False, monitor_parameters=False)
    result = Fitter().fit(plan, curves, models)
    assert result.success
    resumed = copy.deepcopy(plan)
    resumed.curve_ids = [c.id for c in curves[2:]]
    assert Fitter().fit(resumed, curves, models).success
    for index, curve in enumerate(curves[1:], start=1):
        components = models[curve.id].components
        assert {c.id for c in components} == {locals_[index].id, peak.id}
        assert components[0].to_dict() == locals_[index].to_dict()
        assert components[1].parameters["center"].value == pytest.approx(.1 * index, abs=1e-4)
