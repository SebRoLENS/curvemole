import numpy as np

from curvemole import Curve, Project
from curvemole.core.serialization import save_project


def test_window_project_lifecycle_is_owned_by_the_session(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.app import CurveMoleMainWindow
    from curvemole.gui.project_session import ProjectSession

    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    app = QApplication.instance() or QApplication([])
    project = Project("saved")
    project.add_curve(Curve("c", np.arange(4.), np.arange(4.)))
    path = save_project(project, tmp_path / "saved.fitproj")
    window = CurveMoleMainWindow()
    replaced = []
    window.projectReplaced.connect(replaced.append)
    try:
        assert isinstance(window.session, ProjectSession)
        window.open_project(path)
        assert window.project.name == "saved" and replaced == [window.project]
        assert window._project_lock is not None and window._project_lock.owns()
        window.new_project()
        assert window.project.name != "saved" and len(replaced) == 2
        assert window._project_lock is None  # the previous project's lock was released
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()


def test_session_methods_have_window_entry_points():
    from curvemole.gui.main_window import MainWindow
    from curvemole.gui.project_session import ProjectSession

    for name in ("new_project", "open_project", "show_recovery_sessions", "_poll_project_lock",
                 "_poll_project_transfer", "_release_lock", "_confirm_discard_or_save"):
        assert callable(getattr(ProjectSession, name))
        assert getattr(MainWindow, name).__module__ == "curvemole.gui.main_window"
