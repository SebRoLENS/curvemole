import sys

from PySide6.QtWidgets import QApplication

from curvemole.core.models import Component
from curvemole.core.registry import default_registry
from curvemole.gui.function_configuration import InitialParametersTable


def test_strict_positivity_floor_is_shown_as_zero_and_round_trips():
    QApplication.instance() or QApplication([])
    registry = default_registry()
    component = Component.create("gaussian")
    table = InitialParametersTable()
    table.populate(component)
    rows = {table.item(row, 0).text(): row for row in range(table.rowCount())}
    floor = component.parameters["sigma"].minimum
    assert floor in {sys.float_info.min, sys.float_info.epsilon}
    assert table.item(rows["sigma"], 2).text() == "0"
    assert table.item(rows["center"], 2).text() == "-inf"
    table.apply(component, registry.get("gaussian"))
    assert component.parameters["sigma"].minimum > 0
