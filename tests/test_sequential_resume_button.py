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

    window._set_sequential_resume_available(True)
    assert window.sequential_resume_button.isHidden() is False
    assert window.sequential_resume_button.isEnabled() is True
    assert window.resume_action.isEnabled() is True

    window._set_sequential_resume_available(False)
    assert window.sequential_resume_button.isHidden() is True
    assert window.sequential_resume_button.isEnabled() is False
    assert window.resume_action.isEnabled() is False

    window.close()
