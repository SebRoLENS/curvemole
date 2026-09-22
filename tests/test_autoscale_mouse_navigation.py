from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from curvemole import Curve, Project, Series
from curvemole.gui.main_window import MainWindow


def test_autoscale_runs_after_mouse_click_on_data_item() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Mouse autoscale")
    first = Curve("First", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    second = Curve("Second", [100.0, 150.0, 200.0], [20.0, 40.0, 30.0])
    project.add_series(Series("Series", [first, second]))
    project.dirty = False

    window = MainWindow(project)
    window.show()
    app.processEvents()

    workspace = window.plot_workspace
    workspace.autoscale_toggle.setChecked(True)
    app.processEvents()

    calls: list[str | None] = []
    original_apply = workspace._apply_autoscale

    def tracked_apply() -> None:
        calls.append(window.active_curve_id)
        original_apply()

    workspace._apply_autoscale = tracked_apply  # type: ignore[method-assign]
    calls.clear()

    # Click the already-active row first. This deliberately avoids relying on
    # activeCurveChanged: the mouse-click autoscale hook itself must fire.
    item = window.curve_tree.topLevelItem(0).child(0)
    rectangle = window.curve_tree.visualItemRect(item)
    QTest.mouseClick(
        window.curve_tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rectangle.center(),
    )
    app.processEvents()
    assert calls == [first.id]

    # Switching to another data item with the mouse must finish with an autoscale
    # for the new active item as well.
    calls.clear()
    item = window.curve_tree.topLevelItem(0).child(1)
    rectangle = window.curve_tree.visualItemRect(item)
    QTest.mouseClick(
        window.curve_tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rectangle.center(),
    )
    app.processEvents()
    assert window.active_curve_id == second.id
    assert calls
    assert calls[-1] == second.id

    project.dirty = False
    window.close()
    app.processEvents()
