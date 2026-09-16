"""Plugin docks created after restoreState must recover their saved placement."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QWidget

from curvemole.core.extensions import Contribution, extensions
from curvemole.gui.plugin_host import PluginHost


@pytest.fixture
def panel_windows(monkeypatch):
    app = QApplication.instance() or QApplication([])
    entry = Contribution("example", "example:panel", "Example", "panels",
                         lambda context: QWidget(), auto_show=True)
    monkeypatch.setattr(extensions, "entries", {entry.identifier: entry})
    windows = []

    def create():
        window = QMainWindow()
        windows.append(window)
        window.resize(1000, 700)
        window.setCentralWidget(QWidget())
        for name in ("File", "Data", "Tools", "View"):
            window.menuBar().addMenu(name)
        window.project = SimpleNamespace(ui_state={})
        window.active_curve_id = None
        window.curve_tree = SimpleNamespace(selected_curve_ids=lambda: [])
        window.plugin_manager = SimpleNamespace(errors={})
        window._thread = None
        window._notify = lambda message: None
        anchor = QDockWidget("Anchor", window)
        anchor.setObjectName("anchor")
        anchor.setWidget(QWidget())
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, anchor)
        window.plugin_host = PluginHost(window)
        window.plugin_host.finish_startup()
        window.show()
        return window, anchor

    yield app, entry, create
    for window in windows:
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("placement", ["left", "bottom", "tabbed", "floating"])
def test_auto_panel_restores_after_main_window_state(panel_windows, placement):
    app, entry, create = panel_windows
    first, anchor = create()
    app.processEvents()
    dock = first.plugin_host.dialogs[entry.identifier]
    assert first.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    area = (Qt.DockWidgetArea.BottomDockWidgetArea if placement == "bottom"
            else Qt.DockWidgetArea.LeftDockWidgetArea)
    first.addDockWidget(area, dock)
    if placement == "tabbed":
        first.tabifyDockWidget(anchor, dock)
    elif placement == "floating":
        dock.setFloating(True)
        dock.setGeometry(120, 140, 360, 280)
    app.processEvents()
    geometry = dock.geometry()
    state = first.saveState()
    first.hide()

    restarted, new_anchor = create()
    # Match startup: automatic plugin docks already exist when state is restored.
    assert entry.identifier in restarted.plugin_host.dialogs
    assert restarted.restoreState(state)
    restored = restarted.plugin_host.dialogs[entry.identifier]
    assert restarted.dockWidgetArea(restored) == area
    assert restored.isVisible()
    assert restored.isFloating() == (placement == "floating")
    if placement == "tabbed":
        assert restored in restarted.tabifiedDockWidgets(new_anchor)
    elif placement == "floating":
        assert restored.geometry() == geometry
