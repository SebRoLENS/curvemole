from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication

from curvemole import Project
from curvemole.gui.app import CurveMoleMainWindow


def test_revert_background_action_discards_qaction_checked_payload() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("revert background action")
    window = CurveMoleMainWindow(project)

    calls: list[tuple[object, ...]] = []
    window.revert_backgrounds = lambda *args: calls.append(args)  # type: ignore[method-assign]

    window.revert_background_action.trigger()
    app.processEvents()

    assert calls == [()]

    project.dirty = False
    window.close()
    app.processEvents()
