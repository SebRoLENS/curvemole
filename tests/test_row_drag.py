import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QListWidgetItem

from curvemole import Curve, Project
from curvemole.core.data import Series
from curvemole.gui.main_window import CurveTree
from curvemole.gui.panels import COMPONENT_CURVE_ROLE, FunctionList


def _functions():
    view = FunctionList()
    for row in range(60):
        item = QListWidgetItem(f"Function {row}", view)
        item.setData(COMPONENT_CURVE_ROLE, "spectrum")
        item.setData(Qt.ItemDataRole.UserRole, str(row))
    return view


@pytest.mark.parametrize("kind", ["series", "spectrum", "function"])
@pytest.mark.parametrize("multiple", [False, True])
def test_wheel_scrolls_held_row_to_new_drop_target(kind, multiple):
    app = QApplication.instance() or QApplication([])
    role = Qt.ItemDataRole.UserRole
    if kind == "function":
        view = _functions()
        source = view.indexFromItem(view.item(1))
        source_id = source.data(role)
        extra = view.item(3)
        extra_id = extra.data(role)
        extra.setData(COMPONENT_CURVE_ROLE, "second spectrum")
    else:
        view = CurveTree()
        project = Project()
        if kind == "series":
            for row in range(60):
                series = Series(f"Series {row}")
                series.add(Curve(f"Spectrum {row}", [0.0, 1.0], [1.0, 2.0]))
                project.add_series(series)
        else:
            series = Series("Series")
            for row in range(60):
                series.add(Curve(f"Spectrum {row}", [0.0, 1.0], [1.0, 2.0]))
            project.add_series(series)
        view.populate(project, None)
        item = view.topLevelItem(1)
        if kind == "spectrum":
            parent = view.topLevelItem(0)
            parent.setExpanded(True)
            item = parent.child(1)
            extra = parent.child(3)
        else:
            extra = view.topLevelItem(3)
        source = view.indexFromItem(item, 1)
        source_id = tuple(source.data(role))
        extra_id = tuple(extra.data(1, role))

    if multiple:
        view.setSelectionMode(view.SelectionMode.ExtendedSelection)
        view.itemFromIndex(source).setSelected(True)
        extra.setSelected(True)

    moves = []
    view.rowMoveRequested.connect(lambda *args: moves.append(args))
    view.resize(360, 220)
    view.show()
    app.processEvents()
    viewport = view.viewport()
    origin = view.visualRect(source).center()
    destination = QPoint(origin.x(), viewport.height() // 2)
    button = Qt.MouseButton.LeftButton
    scrollbar = view.verticalScrollBar()
    try:
        QTest.mousePress(viewport, button, pos=origin)
        QTest.mouseMove(viewport, destination)
        initial_target = view._row_drop.target.data(role)
        scrolled_target = None
        for delta in (-120, 120, -120):
            wheel = QWheelEvent(
                QPointF(destination), QPointF(viewport.mapToGlobal(destination)),
                QPoint(), QPoint(0, delta), button, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            QApplication.sendEvent(viewport, wheel)
            if delta < 0:
                assert scrollbar.value() > 0
                scrolled_target = view._row_drop.target.data(role)
                assert scrolled_target != initial_target
            else:
                assert scrollbar.value() == 0
                assert view._row_drop.target.data(role) == initial_target
        assert not moves
        after = view._row_drop.after
        QTest.mouseRelease(viewport, button, pos=destination)
        if kind == "function":
            assert len(moves) == 1
            actual_curve, actual_source, actual_target, actual_after = moves[0]
            assert (actual_curve, actual_target, actual_after) == ("spectrum", scrolled_target, after)
        else:
            assert len(moves) == 1
            actual_source, actual_target, actual_after = moves[0]
            assert (tuple(actual_target), actual_after) == (tuple(scrolled_target), after)
        if multiple:
            if kind == "function":
                assert set(actual_source) == {("spectrum", source_id), ("second spectrum", extra_id)}
            else:
                assert set(map(tuple, actual_source)) == {source_id, extra_id}
        else:
            assert (actual_source if kind == "function" else tuple(actual_source)) == source_id
        assert view._row_drop is None
    finally:
        view.close()


def test_drag_autoscrolls_at_edge_and_escape_cancels():
    app = QApplication.instance() or QApplication([])
    view = _functions()
    view.resize(360, 220)
    view.show()
    app.processEvents()
    viewport = view.viewport()
    origin = view.visualItemRect(view.item(1)).center()
    edge = QPoint(origin.x(), viewport.height() - 3)
    button = Qt.MouseButton.LeftButton
    scrollbar = view.verticalScrollBar()
    scroll_changes = QSignalSpy(scrollbar.valueChanged)
    moves = []
    view.rowMoveRequested.connect(lambda *args: moves.append(args))
    try:
        QTest.mousePress(viewport, button, pos=origin)
        QTest.mouseMove(viewport, edge)
        initial_target = view._row_drop.target.row()
        assert scroll_changes.wait(1000)
        assert scrollbar.value() > 0
        assert view._row_drop.target.row() > initial_target

        QTest.keyClick(view, Qt.Key.Key_Escape)
        stopped = scrollbar.value()
        QTest.qWait(100)
        assert scrollbar.value() == stopped
        assert view._row_drop is None
        QTest.mouseRelease(viewport, button, pos=edge)
        assert not moves
    finally:
        view.close()
