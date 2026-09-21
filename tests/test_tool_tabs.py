"""Native and plugin tools share the same dock-tab workspace."""

from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from curvemole import Project
from curvemole.gui.main_window import MainWindow


def test_native_tools_are_tabs_and_actions_activate_them():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.show()
    window.reset_layout()
    app.processEvents()

    window.calculator_action.trigger()
    app.processEvents()
    assert not window.calculator_dock.isHidden()
    assert window.calculator_dock.widget() is window.calculator
    assert window.calculator_dock in window.tabifiedDockWidgets(window.model_dock)

    window.function_action.trigger()
    app.processEvents()
    assert not window.function_dock.isHidden()
    assert window.function_dock.widget() is window.function_builder
    tabbed = window.tabifiedDockWidgets(window.model_dock)
    assert window.calculator_dock in tabbed
    assert window.function_dock in tabbed

    window.project.dirty = False
    window.close()


def test_runtime_tool_joins_tabs_and_keeps_widget_when_hidden():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    panel = QWidget()
    dock = QDockWidget("Runtime plugin", window)
    dock.setObjectName("runtime_plugin")
    dock.setWidget(panel)

    window.activate_tool_dock(dock)
    app.processEvents()
    assert dock in window.tabifiedDockWidgets(window.model_dock)
    dock.hide()
    assert dock.widget() is panel
    window.activate_tool_dock(dock)
    assert not dock.isHidden()

    window.project.dirty = False
    window.close()
