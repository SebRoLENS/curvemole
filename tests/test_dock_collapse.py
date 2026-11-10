"""Collapsing a dock area preserves its tool tabs and returns space to the plot."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel

from curvemole import Project
from curvemole.gui.main_window import MainWindow


def test_wide_tool_contents_do_not_set_other_tabs_minimum_width():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.reset_layout()
    window.show()
    app.processEvents()
    window.resizeDocks([window.model_dock], [250], Qt.Orientation.Horizontal)
    app.processEvents()
    width = window.model_dock.width()

    wide = QDockWidget("Wide tool", window)
    wide.setObjectName("WideTool")
    content = QLabel("Wide controls", wide)
    content.setMinimumWidth(900)
    wide.setWidget(content)
    window.activate_tool_dock(wide)
    window.model_dock.raise_()
    window.resizeDocks([window.model_dock], [250], Qt.Orientation.Horizontal)
    app.processEvents()
    assert window.model_dock.width() == width

    wide.raise_()
    app.processEvents()
    assert wide.width() == width
    viewport = wide.widget()
    assert viewport.widget() is content
    assert viewport.horizontalScrollBar().maximum() > 0
    viewport.horizontalScrollBar().setValue(viewport.horizontalScrollBar().maximum())
    assert content.geometry().right() == viewport.viewport().width() - 1
    window.close()


def test_dock_controls_hide_entire_areas_and_restore_tabs_and_active_tool():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.reset_layout()
    window.show()
    window.activate_tool_dock(window.function_dock)
    bottom = QDockWidget("Bottom test", window)
    bottom.setObjectName("BottomTest")
    bottom.setWidget(QLabel("Bottom content", bottom))
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, bottom)
    window.dock_collapse.watch(bottom)
    app.processEvents()

    controls = window.dock_collapse
    for area, docks in (
        (Qt.DockWidgetArea.LeftDockWidgetArea, [window.series_dock]),
        (Qt.DockWidgetArea.RightDockWidgetArea, [window.model_dock, window.function_dock]),
        (Qt.DockWidgetArea.BottomDockWidgetArea, [bottom]),
    ):
        button = controls._buttons[area]
        plot_before = window.centralWidget().size()
        assert button.isVisible()
        button.click()
        app.processEvents()
        assert all(dock.isHidden() for dock in docks)
        assert button.isVisible()
        assert button.accessibleName().startswith("Expand")
        assert window.centralWidget().size() != plot_before

        collapsed = controls.save()
        controls.restore(collapsed)
        button.click()
        app.processEvents()
        assert all(not dock.isHidden() for dock in docks)
        assert button.accessibleName().startswith("Collapse")
    assert window.function_dock in window.tabifiedDockWidgets(window.model_dock)
    assert not window.function_dock.visibleRegion().isEmpty()
    assert window.model_dock.visibleRegion().isEmpty()
    window.close()


def test_collapsed_area_can_be_reopened_after_restoring_window_layout():
    app = QApplication.instance() or QApplication([])
    area = Qt.DockWidgetArea.RightDockWidgetArea
    first = MainWindow(Project())
    first.reset_layout()
    first.show()
    first.activate_tool_dock(first.function_dock)
    app.processEvents()
    first.dock_collapse.toggle(area)
    first.close()

    reopened = MainWindow(Project())
    reopened.show()
    app.processEvents()
    assert reopened.model_dock.isHidden()
    assert reopened.function_dock.isHidden()
    assert reopened.dock_collapse._buttons[area].isVisible()
    reopened.dock_collapse.toggle(area)
    app.processEvents()
    assert not reopened.function_dock.visibleRegion().isEmpty()
    assert not reopened.model_dock.isHidden()
    reopened.close()
