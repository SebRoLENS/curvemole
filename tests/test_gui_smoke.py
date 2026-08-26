from __future__ import annotations

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from curvemole import Component, Curve, Project
from curvemole.gui.main_window import MainWindow
from curvemole.gui.plot import MaskViewBox
from curvemole.version import __version__


def test_main_window_starts_offscreen() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle().endswith(f"CurveMole {__version__}")
    assert window.plot_workspace is not None
    window.close()
    app.processEvents()


def test_component_selection_refresh_does_not_recurse() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Selection")
    curve = Curve("curve", [0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    project.add_curve(curve)
    component = Component.create("gaussian")
    project.model_for(curve.id).add(component)
    project.dirty = False
    window = MainWindow(project)

    window._set_component(component.id)

    assert window.model_panel.selected_component_id() == component.id
    assert window.model_panel.parameters.rowCount() == 3
    window.close()
    app.processEvents()


def test_graphical_peak_and_spline_placement_create_components() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("Placement")
    curve = Curve(
        "curve",
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [1.0, 2.0, 5.0, 2.0, 1.0],
    )
    project.add_curve(curve)
    project.dirty = False
    window = MainWindow(project)

    window._pending_component = Component.create("gaussian")
    window._pending_component_curve_id = curve.id
    window._graphical_peak_placed(2.0, 5.0, 1.2)
    peak = project.model_for(curve.id).components[0]
    assert peak.parameters["center"].value == 2.0
    assert 2.354820045 * peak.parameters["sigma"].value == pytest.approx(1.2)

    window._pending_component = Component.create(
        "cubic_spline", metadata={"x_nodes": [0.0, 4.0]}
    )
    window._pending_component_curve_id = curve.id
    window._graphical_spline_placed([(0.0, 1.0), (2.0, 1.2), (4.0, 1.0)])
    spline = project.model_for(curve.id).components[1]
    assert spline.metadata["x_nodes"] == [0.0, 2.0, 4.0]

    project.dirty = False
    window.close()
    app.processEvents()


def test_right_drag_requests_interval_mask() -> None:
    class TestViewBox(MaskViewBox):
        def mapSceneToView(self, point: QPointF) -> QPointF:
            return point

    class DragEvent:
        accepted = False

        def button(self) -> Qt.MouseButton:
            return Qt.MouseButton.RightButton

        def isFinish(self) -> bool:
            return True

        def buttonDownScenePos(self) -> QPointF:
            return QPointF(1.25, 0.0)

        def scenePos(self) -> QPointF:
            return QPointF(4.75, 0.0)

        def accept(self) -> None:
            self.accepted = True

    view_box = TestViewBox()
    requested: list[tuple[float, float]] = []
    view_box.maskRangeRequested.connect(lambda lower, upper: requested.append((lower, upper)))
    event = DragEvent()

    view_box.mouseDragEvent(event)

    assert requested == [(1.25, 4.75)]
    assert event.accepted
