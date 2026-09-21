"""Native and plugin tools share the same dock-tab workspace."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from curvemole import Project
from curvemole.gui.main_window import MainWindow


def test_old_window_state_is_not_restored_during_layout_migration(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.settings = QSettings(str(tmp_path / "old-layout.ini"), QSettings.Format.IniFormat)
    window.settings.setValue("window_state", b"old dock hierarchy")
    restored = []
    migrated = []
    monkeypatch.setattr(window, "restoreState", lambda state: restored.append(state))
    monkeypatch.setattr(window, "_apply_tabbed_tool_layout", lambda: migrated.append(True))

    window._restore_layout()

    assert restored == []
    assert migrated == [True]
    assert window.settings.value("layout/schema_version", 0, type=int) == 2
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_current_window_state_is_restored_without_migration(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.settings = QSettings(str(tmp_path / "current-layout.ini"), QSettings.Format.IniFormat)
    window.settings.setValue("window_state", b"current dock hierarchy")
    window.settings.setValue("layout/schema_version", window._LAYOUT_SCHEMA_VERSION)
    restored = []
    migrated = []
    monkeypatch.setattr(window, "restoreState", lambda state: restored.append(state) or True)
    monkeypatch.setattr(window, "_apply_tabbed_tool_layout", lambda: migrated.append(True))

    window._restore_layout()

    assert restored == [b"current dock hierarchy"]
    assert migrated == []
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_notebook_placeholder_keeps_a_python_owner():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())

    assert window._notebook_placeholder is not None
    assert window.notebook_dock.widget() is window._notebook_placeholder

    window.project.dirty = False
    window.close()
    app.processEvents()


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


def test_tab_layout_does_not_transiently_show_hidden_tools():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    hidden_tools = [dock for dock in window._tool_docks if dock is not window.model_dock]
    for dock in hidden_tools:
        dock.hide()
    app.processEvents()

    visibility_events = {dock: [] for dock in hidden_tools}
    for dock in hidden_tools:
        dock.visibilityChanged.connect(visibility_events[dock].append)

    window._apply_tabbed_tool_layout()
    app.processEvents()

    assert all(True not in events for events in visibility_events.values())
    assert all(dock.isHidden() for dock in hidden_tools)

    first = hidden_tools[0]
    window.activate_tool_dock(first)
    app.processEvents()
    assert first in window.tabifiedDockWidgets(window.model_dock)
    window.project.dirty = False
    window.close()
