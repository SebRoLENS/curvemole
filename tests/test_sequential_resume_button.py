from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from curvemole.core.project import Project
from curvemole.gui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_sequential_resume_button_is_visible_only_while_paused() -> None:
    _app()
    window = MainWindow(Project())

    assert window.sequential_resume_button.isHidden() is True
    assert window.sequential_resume_button.isEnabled() is False
    assert window.sequential_stop_button.isHidden() is True

    window._set_sequential_resume_available(True)
    assert window.sequential_resume_button.isHidden() is False
    assert window.sequential_resume_button.isEnabled() is True
    assert window.resume_action.isEnabled() is True
    assert window.sequential_stop_button.isEnabled() is True
    assert window.sequential_stop_button.isHidden() is False
    window.apply_theme("light")
    assert "background-color: #0F766E" in window.sequential_resume_button.styleSheet()
    assert "color: #FFFFFF" in window.sequential_resume_button.styleSheet()
    assert "background-color: #BE123C" in window.sequential_stop_button.styleSheet()
    window.apply_theme("dark")
    assert "background-color: #5EEAD4" in window.sequential_resume_button.styleSheet()
    assert "color: #083B36" in window.sequential_resume_button.styleSheet()
    assert "background-color: #FDA4AF" in window.sequential_stop_button.styleSheet()
    window.apply_theme("system")

    window._set_sequential_resume_available(False)
    assert window.sequential_resume_button.isHidden() is True
    assert window.sequential_resume_button.isEnabled() is False
    assert window.resume_action.isEnabled() is False

    window.close()


def test_terminate_button_clears_queue_and_preserves_models_and_results(monkeypatch) -> None:
    from types import SimpleNamespace

    import numpy as np

    from curvemole import Component, Curve

    _app()
    project = Project()
    curve = Curve("corrected", np.arange(5.0), np.ones(5))
    project.add_curve(curve)
    model = project.model_for(curve.id)
    model.add(Component.create("constant", initial={"offset": 2.5}))
    window = MainWindow(project)
    snapshot = model.to_dict()
    results = dict(project.results)
    window._sequential_resume_plan = object()
    window._sequential_pause_result = window._paused_result = SimpleNamespace(paused_curve_id=curve.id)
    window._sequential_pause_source_ids = (model.components[0].id,)
    window.refresh_all()
    assert window.sequential_stop_button.isEnabled()
    # A manual task still owns the model; neither queue control can race it.
    window._thread = object()
    window._set_sequential_resume_available(True)
    assert not window.sequential_stop_button.isEnabled()
    window.terminate_sequence()
    assert window._sequential_pause_result is not None
    window._thread = None
    window._set_sequential_resume_available(True)
    window.sequential_stop_button.click()
    assert window._sequential_resume_plan is None
    assert window._sequential_pause_result is None
    assert window._paused_result is None
    assert window._sequential_pause_source_ids == ()
    assert window.sequential_resume_button.isHidden()
    assert window.sequential_stop_button.isHidden()
    assert not window.resume_action.isEnabled()
    assert model.to_dict() == snapshot
    assert project.results == results
    started = []
    monkeypatch.setattr(window, "_run_fit", lambda plan: started.append(plan))
    window.resume_sequence()
    assert not started
    project.dirty = False
    window.close()
