import numpy as np


def _window():
    from PySide6.QtWidgets import QApplication

    from curvemole import Component, Curve, Project
    from curvemole.gui.app import CurveMoleMainWindow

    app = QApplication.instance() or QApplication([])
    project = Project("p")
    x = np.linspace(0, 10, 400)
    curve = Curve("c", x, 100 * np.exp(-((x - 5) ** 2)) + np.random.default_rng(0).normal(0, 1, x.size))
    project.add_curve(curve)
    window = CurveMoleMainWindow(project)
    window.resize(1200, 800)
    window.show()
    app.processEvents()
    project.model_for(curve.id).add(Component.create("gaussian", initial={"area": 1, "center": 5, "sigma": 1}))
    window.refresh_all()
    app.processEvents()
    return app, window, project, curve


def _close(app, window, project):
    project.dirty = False
    window.close()
    app.processEvents()


def _residual_range(window):
    box = window.plot_workspace.residual_plot.getViewBox()
    box.updateAutoRange()
    return box.viewRange()[1]


def test_residual_axis_follows_new_residuals_after_the_model_changes():
    app, window, project, curve = _window()
    try:
        parameter = project.model_for(curve.id).components[0].parameters["area"]
        parameter.value = 177  # close to the data: residuals shrink to the noise level
        window.refresh_all()
        app.processEvents()
        low, high = _residual_range(window)
        assert high - low < 60
    finally:
        _close(app, window, project)


def test_residual_zoom_chosen_by_hand_is_preserved():
    app, window, project, curve = _window()
    try:
        workspace = window.plot_workspace
        box = workspace.residual_plot.getViewBox()
        box.setYRange(-1000, 1000, padding=0)
        box.sigRangeChangedManually.emit(box.state["mouseEnabled"])
        window.refresh_all()
        app.processEvents()
        low, high = box.viewRange()[1]
        assert (low, high) == (-1000, 1000)
        workspace.auto_range()  # View all hands the axis back to the residuals
        assert not workspace._residual_view_manual
    finally:
        _close(app, window, project)
