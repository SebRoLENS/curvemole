from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QComboBox

import curvemole.core.initialization as initialization
import curvemole.core.plugins as plugins
from curvemole.core.functions import formula_definition
from curvemole.core.initialization import PeakSuggestion
from curvemole.core.models import Component
from curvemole.core.registry import default_registry
from curvemole.gui.panels import FunctionBuilderPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _custom_peak(identifier: str, formula: str, roles: dict[str, str] | None) -> Component:
    registry = default_registry()
    definition = formula_definition(identifier, identifier, formula, kind="peak")
    if roles is not None:
        definition.custom_metadata["peak_roles"] = dict(roles)
    registry.register(definition, replace=True)
    return Component.create(identifier, registry=registry)


def test_explicit_roles_initialise_arbitrarily_named_peak_parameters() -> None:
    component = _custom_peak(
        "role_peak_test",
        "scale / (1 + ((x-pos)/half)**2)",
        {"scale": "height", "pos": "center", "half": "hwhm"},
    )
    suggestion = PeakSuggestion(x=7.5, height=3.0, fwhm=2.4, prominence=3.0, sign=1)

    initialization.initialise_peak_component(component, suggestion)

    assert component.parameters["scale"].value == pytest.approx(3.0)
    assert component.parameters["pos"].value == pytest.approx(7.5)
    assert component.parameters["half"].value == pytest.approx(1.2)
    definition = default_registry().get("role_peak_test")
    values = {name: parameter.value for name, parameter in component.parameters.items()}
    assert definition.evaluate(np.array([7.5]), values, {})[0] == pytest.approx(3.0)


def test_explicit_empty_roles_disable_parameter_name_guessing() -> None:
    component = _custom_peak(
        "role_peak_no_guess_test",
        "A / (1 + ((x-x0)/gamma)**2)",
        {},
    )
    suggestion = PeakSuggestion(x=7.5, height=3.0, fwhm=2.4, prominence=3.0, sign=1)

    initialization.initialise_peak_component(component, suggestion)

    # Formula defaults are all 1.0. Explicitly choosing no roles means CurveMole
    # respects that choice rather than inferring semantics from A/x0/gamma.
    assert component.parameters["A"].value == pytest.approx(1.0)
    assert component.parameters["x0"].value == pytest.approx(1.0)
    assert component.parameters["gamma"].value == pytest.approx(1.0)


def test_legacy_custom_peak_without_role_metadata_keeps_compatibility() -> None:
    component = _custom_peak(
        "legacy_role_peak_test",
        "A / (1 + ((x-x0)/gamma)**2)",
        None,
    )
    suggestion = PeakSuggestion(x=4.0, height=2.5, fwhm=1.6, prominence=2.5, sign=1)

    initialization.initialise_peak_component(component, suggestion)

    assert component.parameters["A"].value == pytest.approx(2.5)
    assert component.parameters["x0"].value == pytest.approx(4.0)
    assert component.parameters["gamma"].value == pytest.approx(0.8)


def test_function_builder_roles_are_only_shown_for_peak_functions() -> None:
    _app()
    panel = FunctionBuilderPanel(default_registry())

    assert panel.peak_roles_table.rowCount() == 3
    assert not panel.peak_roles_table.isHidden()
    assert not panel.peak_roles_note.isHidden()

    panel.kind.setCurrentIndex(panel.kind.findData("generic"))
    assert panel.peak_roles_table.isHidden()
    assert panel.peak_roles_note.isHidden()

    panel.kind.setCurrentIndex(panel.kind.findData("peak"))
    assert not panel.peak_roles_table.isHidden()


def test_builder_role_selection_tracks_formula_parameters() -> None:
    _app()
    panel = FunctionBuilderPanel(default_registry())
    panel.formula.setPlainText("scale / (1 + ((x-pos)/half)**2)")

    wanted = {"scale": "height", "pos": "center", "half": "hwhm"}
    for row in range(panel.peak_roles_table.rowCount()):
        name = panel.peak_roles_table.item(row, 0).text()
        combo = panel.peak_roles_table.cellWidget(row, 1)
        assert isinstance(combo, QComboBox)
        combo.setCurrentIndex(combo.findData(wanted[name]))

    assert panel.peak_parameter_roles() == wanted


def test_peak_roles_round_trip_through_custom_function_json(tmp_path) -> None:
    definition = formula_definition(
        "role_round_trip_test",
        "Role round trip",
        "scale / (1 + ((x-pos)/half)**2)",
        kind="peak",
    )
    definition.custom_metadata["peak_roles"] = {
        "scale": "height",
        "pos": "center",
        "half": "hwhm",
    }
    destination = tmp_path / "role_round_trip_test.curvemole-function.json"

    plugins.export_custom_function(definition, destination)
    loaded = plugins.import_custom_function(destination)

    assert loaded.custom_metadata["peak_roles"] == definition.custom_metadata["peak_roles"]
