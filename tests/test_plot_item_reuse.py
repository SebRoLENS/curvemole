"""Redraws reuse core scene items without retaining obsolete data or callbacks."""
import numpy as np
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.core.registry import default_registry
from curvemole.gui.app import PlotWorkspace


def test_reused_items_receive_new_data_styles_and_only_one_click_connection():
    app = QApplication.instance() or QApplication([])
    project = Project()
    curve = Curve("Measured", np.arange(30.), np.arange(30.) * 2)
    project.add_curve(curve)
    component = Component.create("linear", initial={"slope": 2, "intercept": 0})
    project.model_for(curve.id).add(component)
    workspace = PlotWorkspace(default_registry())
    workspace.set_context(project, curve.id)
    key = (curve.id, component.id)
    data_item = workspace._data_items[curve.id]
    component_item = workspace._component_items[key]
    workspace.set_plot_appearance({"data_style": "points"})
    assert workspace._data_items[curve.id] is data_item
    assert data_item.opts["symbol"] is not None
    workspace.set_plot_appearance({"data_style": "lines"})
    assert data_item.opts["symbol"] is None
    clicked = []
    workspace.componentOnCurveSelected.connect(lambda *args: clicked.append(args))
    component.parameters["slope"].value = 3
    for _ in range(5):
        workspace.refresh()
        assert workspace._data_items[curve.id] is data_item
        assert workspace._component_items[key] is component_item
        np.testing.assert_allclose(component_item.getOriginalDataset()[1], curve.x * 3)
        assert len(workspace._render_items) == 4
    component_item.sigClicked.emit(component_item, None)
    assert clicked == [(curve.id, component.id)]
    project.model_for(curve.id).components.clear()
    workspace.refresh()
    assert len(workspace._render_items) == 1
    assert component_item not in workspace.plot.items
    project.remove_curve(curve.id)
    workspace.refresh()
    assert not workspace._render_items
    assert not workspace.plot.listDataItems()
    workspace.close()
    app.processEvents()
