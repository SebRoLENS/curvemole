import json
import sys

import numpy as np
import pytest

from curvemole.core.errors import FitError
from curvemole.core.extensions import (
    ExtensionRegistry,
    current_extensions,
    extensions,
    use_extensions,
)
from curvemole.core.plugins import PluginManager
from curvemole.plugin_api import PLUGIN_API_VERSION, is_compatible, parse_api_version


def _plugin(tmp_path, body, *, api="1", name="contract"):
    (tmp_path / f"{name}.py").write_text(body)
    manifest = {"identifier": name, "version": "1", "api_compatibility": api,
                "licence": "MIT", "capabilities": ["exporters"], "module": f"{name}.py"}
    (tmp_path / f"{name}.curvemole-plugin.json").write_text(json.dumps(manifest))
    return PluginManager().discover_local(tmp_path)[0]


def test_semantic_api_compatibility():
    assert parse_api_version("1") == (1, 0) and parse_api_version("1.3") == (1, 3)
    assert is_compatible("1", "1") and is_compatible("1.0", "1.2")
    assert not is_compatible("1.3", "1.2")  # needs a newer minor version
    assert not is_compatible("2", "1") and not is_compatible("x", "1")
    assert parse_api_version(PLUGIN_API_VERSION)[0] == 1


def test_newer_or_other_major_api_is_refused(tmp_path):
    item = _plugin(tmp_path, "def register(api):\n pass\n", api="2")
    with pytest.raises(Exception, match="targets API 2"):
        PluginManager().load(item, trust=True)


def test_loaded_plugin_module_is_importable_by_name(tmp_path):
    item = _plugin(tmp_path, "import dataclasses\n@dataclasses.dataclass\nclass Point:\n x: float = 0\n"
                             "def register(api):\n pass\n")
    PluginManager().load(item, trust=True)
    module = sys.modules["curvemole_plugin_contract"]
    assert module.Point(1.0).x == 1.0


def test_injected_extension_registry_isolates_solvers():
    from curvemole.core.data import Curve
    from curvemole.core.fitting import FitPlan, FitSettings, Fitter
    from curvemole.core.models import Component, Model
    from curvemole.plugin_api import Contribution

    def solve(request):
        from scipy.optimize import least_squares
        return least_squares(request.residual, request.initial, bounds=request.bounds,
                             jac=request.jacobian, max_nfev=request.settings.max_nfev)

    private = ExtensionRegistry()
    private.entries["private:solver"] = Contribution("private", "private:solver", "Private", "fit_solvers", solve)
    x = np.linspace(-5, 5, 51)
    curve = Curve("line", x, 3 * x + 2)
    model = Model(components=[Component.create("linear")])
    plan = FitPlan([curve.id], settings=FitSettings(solver="private:solver"))
    assert current_extensions() is extensions
    with pytest.raises(FitError, match="Unknown solver"):
        Fitter().fit(plan, [curve], {curve.id: model.clone()})
    result = Fitter(extensions=private).fit(plan, [curve], {curve.id: model.clone()})
    assert result.success
    assert current_extensions() is extensions  # restored after the fit
    with use_extensions(private):
        assert current_extensions() is private


def test_block_resampler_is_public_and_the_private_name_remains():
    from curvemole.core import uncertainty

    assert uncertainty._sample_residual_blocks is uncertainty.sample_residual_blocks
    sample = uncertainty.sample_residual_blocks(np.random.default_rng(0), np.arange(10.), 3, circular=False)
    assert len(sample) == 10
