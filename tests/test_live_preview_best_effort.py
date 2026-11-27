import numpy as np


def test_live_preview_errors_from_other_curves_do_not_fail_the_fit(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curvemole import Component, Curve, Project
    from curvemole.core import live_fit_progress
    from curvemole.core.data import CurveState
    from curvemole.core.fitting import FitMode, FitPlan
    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(live_fit_progress, "LIVE_REFRESH_EVERY", 1)
    monkeypatch.setattr(live_fit_progress, "LIVE_PREVIEW_SECONDS", 0.)
    project = Project("p")
    x = np.linspace(-5, 5, 201)
    a = Curve("A", x, 3 * np.exp(-0.5 * (x / 0.8) ** 2) + 0.2)
    b = Curve("B", x, 2 * np.exp(-0.5 * (x / 0.8) ** 2))
    project.add_curve(a)
    project.add_curve(b)
    first = Component.create("gaussian", initial={"area": 1.0})
    second = Component.create("gaussian", initial={"area": 1.0})
    project.model_for(a.id).add(first)
    project.model_for(b.id).add(second)
    linked = project.model_for(b.id).component(second.id).parameters["area"]
    linked.maximum = 1.5  # A's fitted area exceeds B's bound while A is still running
    linked.link = "${%s.%s.area}" % (a.id, first.id)
    linked.link_scope = "absolute"
    linked.validate()
    window = MainWindow(project)
    window._show_error = lambda *_: None

    def synchronous(operation, finished, status, partial=None):
        finished(operation(lambda *_: None, partial))

    monkeypatch.setattr(window, "_run_background", synchronous)
    window._run_fit(FitPlan([a.id, b.id], FitMode.INDEPENDENT))
    assert project.dataset.curve(a.id).state == CurveState.FITTED
    window._reset_task_state()
    project.dirty = False
    window.close()
    app.processEvents()
