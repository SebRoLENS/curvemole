import json

from curvemole.core.functions import formula_definition
from curvemole.core.initialization import PeakSuggestion, initialise_peak_component
from curvemole.core.models import Component
from curvemole.core.peak_roles import attach_roles
from curvemole.core.plugins import import_custom_function
from curvemole.core.registry import default_registry


def _registry_with(definition):
    registry = default_registry().copy()
    registry.register_custom(definition, replace=True)
    return registry


def test_core_initialisation_uses_declared_roles_without_the_gui():
    # Parameter names deliberately give the legacy name-based guesser nothing to go on.
    definition = formula_definition("bump", "Bump", "q * exp(-((x - p) / r) ** 2)", kind="peak",
                                    defaults={"q": 1, "p": 0, "r": 1})
    attach_roles(definition, {"q": "height", "p": "center", "r": "hwhm", "ignored": "center"})
    assert definition.custom_metadata["peak_roles"] == {"q": "height", "p": "center", "r": "hwhm"}
    registry = _registry_with(definition)
    component = Component.create("bump", registry=registry)
    suggestion = PeakSuggestion(x=42.0, height=7.0, fwhm=4.0, prominence=7.0, sign=1)
    initialise_peak_component(component, suggestion, registry=registry)
    values = {name: parameter.value for name, parameter in component.parameters.items()}
    assert values == {"q": 7.0, "p": 42.0, "r": 2.0}


def test_function_files_and_project_functions_keep_their_roles(tmp_path):
    path = tmp_path / "bump.cmfunction.json"
    path.write_text(json.dumps({
        "format": "CurveMole custom function", "schema_version": 1, "identifier": "bump",
        "display_name": "Bump", "formula": "q * exp(-((x - p) / r) ** 2)", "kind": "peak",
        "defaults": {"q": 1, "p": 0, "r": 1}, "peak_roles": {"p": "center"},
    }))
    assert import_custom_function(path).custom_metadata["peak_roles"] == {"p": "center"}
    registry = default_registry().copy()
    registry.set_project_functions([{"identifier": "bump", "formula": "q * exp(-((x - p) / r) ** 2)",
                                     "kind": "peak", "peak_roles": {"r": "fwhm"}}])
    assert registry.get("bump").custom_metadata["peak_roles"] == {"r": "fwhm"}
