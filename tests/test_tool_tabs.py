"""Native and plugin tools share the same dock-tab workspace."""

import pytest
from PySide6.QtCore import QSettings, QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QTabBar, QToolButton, QWidget

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
    assert window.notebook_dock.widget().widget() is window._notebook_placeholder

    window.project.dirty = False
    window.close()
    app.processEvents()


@pytest.mark.parametrize("large_font", [False, True])
def test_tool_tabs_scroll_and_limit_labels_without_losing_full_titles(large_font):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.resize(960, 640)
    window.show()
    titles = [f"Long plugin panel title number {i}" for i in range(5)]
    for index, title in enumerate(titles):
        dock = QDockWidget(title, window)
        dock.setObjectName(f"scroll_test_{index}")
        dock.setWidget(QWidget())
        window.activate_tool_dock(dock)
    for _ in range(3):
        app.processEvents()
    bar = next(bar for bar in window.findChildren(QTabBar) if bar.parent() is window)
    if large_font:
        font = bar.font()
        font.setPointSize(24)
        bar.setFont(font)
        window.resizeDocks([window.model_dock], [260], Qt.Orientation.Horizontal)
        for _ in range(3):
            app.processEvents()
    assert bar.usesScrollButtons()
    assert bar.elideMode() == Qt.TextElideMode.ElideNone
    assert all(len(bar.tabText(i)) <= 25 for i in range(bar.count()))
    assert all(bar.tabText(i).endswith("...") for i in range(bar.count() - 5, bar.count()))
    assert [bar.tabToolTip(i) for i in range(bar.count() - 5, bar.count())] == titles
    assert bar.tabRect(0).x() < 0 or bar.tabRect(bar.count() - 1).right() > bar.width()
    left = bar.findChild(QToolButton, "ScrollLeftButton")
    right = bar.findChild(QToolButton, "ScrollRightButton")
    for button in (left, right):
        assert button.isVisible() and button.width() >= 26
        assert button.accessibleName() and button.toolTip()
    # Every tab must fit between the arrows. Qt cannot scroll past a tab
    # that starts at the viewport edge and extends under the right button.
    available = bar.width() - left.width() - right.width()
    assert max(bar.tabRect(i).width() for i in range(bar.count())) <= available
    assert left.isEnabled()
    offset = bar.tabRect(0).x()
    current = bar.currentIndex()
    left.click()
    app.processEvents()
    offset_after_left = bar.tabRect(0).x()
    assert offset_after_left > offset
    assert bar.currentIndex() == current
    assert right.isEnabled()
    right.click()
    app.processEvents()
    # Qt's native scroll step can depend on tab widths and the platform style.
    assert bar.tabRect(0).x() < offset_after_left
    assert bar.currentIndex() == current
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_moved_series_dock_keeps_its_title_when_tabs_are_reordered():
    from shiboken6 import getCppPointer

    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.reset_layout()
    window.show()
    window.activate_tool_dock(window.calculator_dock)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.series_dock)
    window.tabifyDockWidget(window.model_dock, window.series_dock)
    window.series_dock.raise_()
    app.processEvents()

    bar = next(bar for bar in window.findChildren(QTabBar) if bar.parent() is window)
    series_id = getCppPointer(window.series_dock)[0]
    index = next(index for index in range(bar.count()) if bar.tabData(index) == series_id)
    with QSignalBlocker(bar):
        bar.moveTab(index, 0)
        window._tool_tab_filter.format_titles(bar)

    assert bar.tabData(0) == series_id
    assert bar.tabText(0) == "Series and curves"
    assert bar.tabToolTip(0) == "Series and curves"
    window.close()


def test_native_tools_are_tabs_and_actions_activate_them():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project())
    window.show()
    window.reset_layout()
    app.processEvents()

    window.calculator_action.trigger()
    app.processEvents()
    assert not window.calculator_dock.isHidden()
    assert window.calculator_dock.widget().widget() is window.calculator
    assert window.calculator_dock in window.tabifiedDockWidgets(window.model_dock)

    window.function_action.trigger()
    app.processEvents()
    assert not window.function_dock.isHidden()
    assert window.function_dock.widget().widget() is window.function_builder
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
    assert dock.widget().widget() is panel
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
