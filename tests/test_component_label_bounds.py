import numpy as np


def test_labels_of_the_tallest_peak_stay_inside_the_plot():
    from PySide6.QtWidgets import QApplication

    from curvemole import Component, Curve, Project
    from curvemole.gui.app import CurveMoleMainWindow

    app = QApplication.instance() or QApplication([])
    project = Project("labels")
    x = np.linspace(0, 100, 1000)
    curve = Curve("c", x, 100 * np.exp(-0.5 * ((x - 50) / 2) ** 2))
    project.add_curve(curve)
    project.model_for(curve.id).add(Component.create("gaussian", initial={"area": 501, "center": 50, "sigma": 2}))
    window = CurveMoleMainWindow(project)
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    try:
        workspace = window.plot_workspace
        workspace.auto_range()
        app.processEvents()
        workspace._layout_component_labels()
        top = workspace.view_box.sceneBoundingRect().top()
        assert workspace._component_label_specs
        for label, *_ in workspace._component_label_specs:
            assert label.sceneBoundingRect().top() >= top - 4
    finally:
        project.dirty = False
        window.close()
        app.processEvents()
